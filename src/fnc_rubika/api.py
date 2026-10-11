"""Dynamic access to every reviewed operation in the active catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .contracts import ContractRegistry
from .exceptions import UnsupportedOperationError
from .models import QueuedOperation

if TYPE_CHECKING:
    from .client import AsyncClient


class ApiNamespace:
    """A lazy namespace allowing ``client.api.messages.send(chat_id=..., text=...)``."""

    def __init__(self, api: "CatalogApi", operation: str = "") -> None:
        self._api = api
        self._operation = operation

    def __getattr__(self, part: str) -> "ApiNamespace":
        if part.startswith("_"):
            raise AttributeError(part)
        operation = f"{self._operation}.{part}" if self._operation else part
        prefix = f"{operation}."
        if operation not in self._api.operations and not any(value.startswith(prefix) for value in self._api.operations):
            raise AttributeError(f"No reviewed API operation named {operation!r}")
        return ApiNamespace(self._api, operation)

    async def __call__(self, *, wait: bool = True, timeout: float | None = 30, **payload: Any) -> Mapping[str, Any] | QueuedOperation:
        if not self._operation:
            raise TypeError("Select a reviewed operation before calling client.api")
        return await self._api.call(self._operation, payload, wait=wait, timeout=timeout)


class CatalogApi(ApiNamespace):
    """Generic, no-hard-code gateway for all catalogued provider operations."""

    def __init__(self, client: "AsyncClient", registry: ContractRegistry) -> None:
        self._client = client
        self._registry = registry
        self.operations = frozenset(registry.operations())
        super().__init__(self)

    async def call(
        self,
        operation: str,
        payload: Mapping[str, Any] | None = None,
        *,
        wait: bool = True,
        timeout: float | None = 30,
        **keyword_payload: Any,
    ) -> Mapping[str, Any] | QueuedOperation:
        spec = self._registry.endpoint(operation)
        request = dict(payload or {})
        request.update(keyword_payload)
        if spec.operation_kind == "mutation":
            return await self._client._submit(operation, request, wait=wait, timeout=timeout)
        if spec.operation_kind == "read":
            return await self._client._read(operation, request)
        raise UnsupportedOperationError(f"Operation {operation!r} has invalid kind {spec.operation_kind!r}")
