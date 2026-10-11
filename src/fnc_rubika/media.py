"""Media operations. Upload is durable when the referenced local file remains available."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import MediaRef, QueuedOperation

if TYPE_CHECKING:
    from .client import AsyncClient


class MediaService:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def upload(self, path: str | Path, *, content_type: str | None = None, wait: bool = True, timeout: float | None = 60) -> MediaRef | QueuedOperation:
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        result = await self._client._submit(
            "media.upload",
            {"file_path": str(file_path.resolve()), "content_type": content_type},
            wait=wait,
            timeout=timeout,
        )
        if isinstance(result, QueuedOperation):
            return result
        raw = result.get("media", result)
        return MediaRef.from_dict(raw)

    async def download(self, file_id: str, destination: str | Path) -> MediaRef:
        target = Path(destination)
        result = await self._client.transport.download(file_id, target)
        return MediaRef.from_dict(result)
