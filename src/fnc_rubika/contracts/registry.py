"""Versioned, reviewed endpoint contracts.  No provider URLs are guessed here."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from ..exceptions import ContractError, UnsupportedOperationError


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    operation: str
    method: str
    path: str
    auth: bool = True
    idempotency_header: str | None = None
    success_statuses: tuple[int, ...] = (200,)
    pagination: Mapping[str, Any] | None = None
    request_schema: Mapping[str, Any] | None = None
    response_schema: Mapping[str, Any] | None = None
    errors: Mapping[str, Any] | None = None
    body_mode: str = "json"
    file_field: str = "file"
    operation_kind: str = "read"
    rpc_method: str | None = None
    dc_type: str = "api"
    target_url: str | None = None
    api_version: str | None = None
    wire_mode: str = "encrypted"
    target_url_field: str | None = None

    @property
    def supports_idempotency(self) -> bool:
        return self.idempotency_header is not None


@dataclass(frozen=True, slots=True)
class WebSocketSpec:
    url: str
    event_id_field: str
    event_type_field: str
    payload_field: str
    cursor_field: str | None = None
    resume_parameter: str | None = None
    heartbeat_seconds: float | None = None
    heartbeat_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AuthenticationSpec:
    """Field mappings for the reviewed OTP endpoints; no provider value is assumed."""

    request_code_operation: str
    verify_code_operation: str
    phone_field: str = "phone_number"
    challenge_field: str = "challenge_id"
    code_field: str = "code"
    token_field: str = "access_token"
    device_id_field: str | None = None
    expires_at_field: str | None = None


class ContractRegistry:
    """Loads only explicitly reviewed contract catalogs from JSON."""

    def __init__(self, *, version: str, base_url: str, endpoints: Mapping[str, EndpointSpec], websocket: WebSocketSpec | None = None, authentication: AuthenticationSpec | None = None, protocol: str = "generic", provider: Mapping[str, Any] | None = None) -> None:
        self.version = version
        self.base_url = base_url.rstrip("/")
        self._endpoints = dict(endpoints)
        self.websocket = websocket
        self.authentication = authentication
        self.protocol = protocol
        self.provider = dict(provider or {})

    @classmethod
    def from_file(cls, path: str | Path) -> "ContractRegistry":
        source = Path(path)
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError("Unable to load the reviewed contract catalog") from exc
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContractRegistry":
        try:
            endpoints = {
                str(item["operation"]): EndpointSpec(
                    operation=str(item["operation"]),
                    method=str(item["method"]).upper(),
                    path=str(item["path"]),
                    auth=bool(item.get("auth", True)),
                    idempotency_header=item.get("idempotency_header"),
                    success_statuses=tuple(item.get("success_statuses", [200])),
                    pagination=item.get("pagination"),
                    request_schema=item.get("request_schema"),
                    response_schema=item.get("response_schema"),
                    errors=item.get("errors"),
                    body_mode=str(item.get("body_mode", "json")),
                    file_field=str(item.get("file_field", "file")),
                    operation_kind=str(item.get("operation_kind", "read")),
                    rpc_method=item.get("rpc_method"),
                    dc_type=str(item.get("dc_type", "api")),
                    target_url=item.get("target_url"),
                    api_version=item.get("api_version"),
                    wire_mode=str(item.get("wire_mode", "encrypted")),
                    target_url_field=item.get("target_url_field"),
                )
                for item in value.get("endpoints", [])
            }
            invalid_kinds = [name for name, endpoint in endpoints.items() if endpoint.operation_kind not in {"read", "mutation"}]
            if invalid_kinds:
                raise ValueError(f"Invalid operation kind for {', '.join(invalid_kinds)}")
            ws_value = value.get("websocket")
            websocket = WebSocketSpec(**ws_value) if ws_value else None
            auth_value = value.get("authentication")
            authentication = AuthenticationSpec(**auth_value) if auth_value else None
            return cls(
                version=str(value["version"]),
                base_url=str(value["base_url"]),
                endpoints=endpoints,
                websocket=websocket,
                authentication=authentication,
                protocol=str(value.get("protocol", "generic")),
                provider=value.get("provider"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("The contract catalog has an invalid shape") from exc

    def endpoint(self, operation: str) -> EndpointSpec:
        try:
            return self._endpoints[operation]
        except KeyError as exc:
            raise UnsupportedOperationError(f"No reviewed contract exists for {operation!r}") from exc

    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._endpoints))

    def require_authentication(self) -> AuthenticationSpec:
        if self.authentication is None:
            raise ContractError("The active catalog has no reviewed OTP authentication contract")
        return self.authentication
