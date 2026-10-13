"""Media operations. Upload is durable when the referenced local file remains available."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .messages import normalize_chat_id
from .models import Message, MediaRef, QueuedOperation

if TYPE_CHECKING:
    from .client import AsyncClient


class MediaService:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def upload_photo(self, path: str | Path, *, timeout: float | None = 300) -> MediaRef:
        """Upload a photo with dimensions and a preview for reuse in send_photo."""
        return await self._upload_visual(path, 'Image', timeout=timeout)

    async def upload_video(self, path: str | Path, *, timeout: float | None = 300) -> MediaRef:
        """Upload a video with dimensions, duration and a preview for send_video."""
        return await self._upload_visual(path, 'Video', timeout=timeout)

    async def _upload_visual(self, path: str | Path, kind: str, *, timeout: float | None) -> MediaRef:
        from .media_metadata import photo_metadata, video_metadata

        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        if file_path.stat().st_size == 0:
            raise ValueError('Cannot upload an empty file')
        inspect_media = photo_metadata if kind == 'Image' else video_metadata
        metadata = await asyncio.to_thread(inspect_media, file_path)
        content_type = mimetypes.guess_type(file_path.name)[0]
        uploaded = await self.upload(file_path, content_type=content_type, timeout=timeout)
        assert isinstance(uploaded, MediaRef)
        descriptor = {**uploaded.raw, **metadata, 'file_name': file_path.name,
                      'mime': file_path.suffix.lstrip('.').lower()}
        return MediaRef.from_dict(descriptor)

    async def send_photo(self, chat_id: str, photo: str | Path | MediaRef, *, caption: str | None = None,
                         reply_to_message_id: str | None = None, wait: bool = True,
                         timeout: float | None = 300) -> Message | QueuedOperation:
        """Send a local or uploaded photo, optionally with a caption.

        Upload completes before queuing, including with wait=False. The timeout
        applies separately to upload and message confirmation.
        """
        return await self._send_visual(chat_id, photo, 'Image', caption=caption,
                                       reply_to_message_id=reply_to_message_id, wait=wait, timeout=timeout)

    async def send_video(self, chat_id: str, video: str | Path | MediaRef, *, caption: str | None = None,
                         reply_to_message_id: str | None = None, wait: bool = True,
                         timeout: float | None = 300) -> Message | QueuedOperation:
        """Send a local or uploaded video, optionally with a caption.

        Upload completes before queuing, including with wait=False. The timeout
        applies separately to upload and message confirmation.
        """
        return await self._send_visual(chat_id, video, 'Video', caption=caption,
                                       reply_to_message_id=reply_to_message_id, wait=wait, timeout=timeout)

    async def _send_visual(self, chat_id: str, media: str | Path | MediaRef, kind: str, *, caption: str | None,
                           reply_to_message_id: str | None, wait: bool, timeout: float | None) -> Message | QueuedOperation:
        chat_id = normalize_chat_id(chat_id)
        if caption is not None and not isinstance(caption, str):
            raise TypeError('caption must be a string or None')
        uploaded = media if isinstance(media, MediaRef) else await self._upload_visual(media, kind, timeout=timeout)
        descriptor = uploaded.raw
        required = ('file_id', 'dc_id', 'access_hash_rec', 'file_name', 'mime', 'size', 'width', 'height')
        if descriptor.get('type') != kind or any(descriptor.get(key) in (None, '') for key in required):
            raise ValueError('Use the matching upload_photo/upload_video result as the media reference')
        if kind == 'Video' and not descriptor.get('time'):
            raise ValueError('The uploaded video reference is missing its duration')
        fields = (*required, 'type', 'thumb_inline', 'time')
        file_inline = {key: descriptor[key] for key in fields if key in descriptor}
        return await self._client.messages._send_media(chat_id, file_inline, caption=caption,
                                                      reply_to_message_id=reply_to_message_id, wait=wait, timeout=timeout)

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

    async def download(self, file_id: str | Mapping[str, Any] | MediaRef, destination: str | Path) -> MediaRef:
        target = Path(destination)
        await self._client.start()
        transport = self._client.transport
        from .exceptions import SessionExpiredError
        try:
            result = await transport.download(file_id, target)
        except SessionExpiredError as exc:
            await self._client._recover_session(transport, exc)
            result = await self._client.transport.download(file_id, target)
        return MediaRef.from_dict(result)
