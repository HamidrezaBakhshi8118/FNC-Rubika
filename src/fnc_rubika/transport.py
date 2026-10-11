"""Contract-driven HTTP/WebSocket transport; it has no hard-coded provider routes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
import inspect
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import websockets

from .contracts import ContractRegistry
from .exceptions import AmbiguousDeliveryError, RateLimitError, RemoteOperationError, SessionExpiredError, TransportError
from .models import Session


class Transport(Protocol):
    async def request(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str) -> Mapping[str, Any]: ...

    async def stream_events(self, cursor: str | None) -> AsyncIterator[Mapping[str, Any]]: ...

    async def download(self, file_id: str, destination: Path) -> Mapping[str, Any]: ...

    async def aclose(self) -> None: ...


def _extract(value: Mapping[str, Any], field: str) -> Any:
    current: Any = value
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise TransportError(f"The realtime frame is missing required field {field!r}")
        current = current[part]
    return current


class HttpWebSocketTransport:
    """Generic adapter activated only by a reviewed :class:`ContractRegistry`."""

    def __init__(
        self,
        registry: ContractRegistry,
        session: Session,
        *,
        timeout: float = 30,
        max_connections: int = 20,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
    ) -> None:
        self._registry = registry
        self._session = session
        self._auth_header = auth_header
        self._auth_prefix = auth_prefix
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
        )

    @property
    def registry(self) -> ContractRegistry:
        return self._registry

    def _headers(self, *, authenticated: bool, idempotency_header: str | None = None, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers[self._auth_header] = f"{self._auth_prefix}{self._session.access_token}"
        if idempotency_header and idempotency_key:
            headers[idempotency_header] = idempotency_key
        return headers

    async def request(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str) -> Mapping[str, Any]:
        endpoint = self._registry.endpoint(operation)
        url = f"{self._registry.base_url}{endpoint.path}"
        headers = self._headers(
            authenticated=endpoint.auth,
            idempotency_header=endpoint.idempotency_header,
            idempotency_key=idempotency_key,
        )
        try:
            if endpoint.body_mode == "json":
                response = await self._http.request(endpoint.method, url, json=dict(payload), headers=headers)
            elif endpoint.body_mode == "multipart":
                form = dict(payload)
                path_value = form.pop("file_path", None)
                if not isinstance(path_value, str):
                    raise TransportError("The reviewed media contract requires a file_path payload field")
                path = Path(path_value)
                with path.open("rb") as handle:
                    response = await self._http.request(
                        endpoint.method,
                        url,
                        data={key: str(value) for key, value in form.items() if value is not None},
                        files={endpoint.file_field: (path.name, handle)},
                        headers=headers,
                    )
            else:
                raise TransportError(f"Unsupported reviewed request body mode {endpoint.body_mode!r}")
        except OSError as exc:
            raise TransportError("The media file could not be opened") from exc
        except httpx.TimeoutException as exc:
            raise AmbiguousDeliveryError("The request timed out before delivery could be confirmed") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise TransportError("The HTTP request failed") from exc
        except httpx.HTTPError as exc:
            raise AmbiguousDeliveryError("The connection ended before delivery could be confirmed") from exc
        return self._decode_response(response, endpoint.success_statuses)

    def supports_idempotency(self, operation: str) -> bool:
        return self._registry.endpoint(operation).supports_idempotency

    def _decode_response(self, response: httpx.Response, success_statuses: tuple[int, ...]) -> Mapping[str, Any]:
        if response.status_code in (401, 403):
            raise SessionExpiredError("The provider rejected the current session")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else None
            except ValueError:
                delay = None
            raise RateLimitError(delay)
        if response.status_code not in success_statuses:
            raise RemoteOperationError(f"Provider returned HTTP {response.status_code}")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise TransportError("The provider returned a non-JSON response") from exc
        if not isinstance(body, Mapping):
            raise TransportError("The provider returned an invalid JSON response")
        return body

    async def stream_events(self, cursor: str | None) -> AsyncIterator[Mapping[str, Any]]:
        spec = self._registry.websocket
        if spec is None:
            raise TransportError("The contract catalog has no WebSocket specification")
        url = spec.url
        if cursor and spec.resume_parameter:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({spec.resume_parameter: cursor})}"
        headers = self._headers(authenticated=True)
        try:
            header_argument = "additional_headers" if "additional_headers" in inspect.signature(websockets.connect).parameters else "extra_headers"
            async with websockets.connect(url, **{header_argument: headers}, ping_interval=None) as websocket:
                while True:
                    try:
                        raw = await asyncio.wait_for(websocket.recv(), timeout=spec.heartbeat_seconds)
                    except TimeoutError:
                        if spec.heartbeat_payload is None:
                            raise TransportError("The WebSocket heartbeat elapsed without a configured heartbeat frame")
                        await websocket.send(json.dumps(spec.heartbeat_payload, separators=(",", ":")))
                        continue
                    if not isinstance(raw, str):
                        raise TransportError("Binary realtime frames require an explicit reviewed decoder")
                    try:
                        frame = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise TransportError("The realtime service returned invalid JSON") from exc
                    if not isinstance(frame, Mapping):
                        continue
                    yield {
                        "event_id": str(_extract(frame, spec.event_id_field)),
                        "type": str(_extract(frame, spec.event_type_field)),
                        "payload": _extract(frame, spec.payload_field),
                        "cursor": str(_extract(frame, spec.cursor_field)) if spec.cursor_field else None,
                    }
        except SessionExpiredError:
            raise
        except websockets.InvalidStatus as exc:
            if getattr(exc, "response", None) and exc.response.status_code in (401, 403):
                raise SessionExpiredError("The provider rejected the current realtime session") from exc
            raise TransportError("The realtime connection was rejected") from exc
        except (OSError, websockets.WebSocketException) as exc:
            raise TransportError("The realtime connection failed") from exc

    async def download(self, file_id: str, destination: Path) -> Mapping[str, Any]:
        endpoint = self._registry.endpoint("media.download")
        path = endpoint.path.format(file_id=file_id)
        url = f"{self._registry.base_url}{path}"
        try:
            response = await self._http.request(endpoint.method, url, headers=self._headers(authenticated=endpoint.auth))
        except httpx.HTTPError as exc:
            raise TransportError("The media download failed") from exc
        if response.status_code in (401, 403):
            raise SessionExpiredError("The provider rejected the current session")
        if response.status_code not in endpoint.success_statuses:
            raise RemoteOperationError(f"Provider returned HTTP {response.status_code} while downloading media")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return {"file_id": file_id, "path": str(destination), "size": len(response.content)}

    async def aclose(self) -> None:
        await self._http.aclose()
