"""Stable message operations implemented through the durable outbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

from .models import Message, QueuedOperation

if TYPE_CHECKING:
    from .client import AsyncClient


def normalize_chat_id(value: str) -> str:
    """Return a Rubika object GUID from a GUID, web hash, or web URL."""

    candidate = value.strip()
    if "#" in candidate:
        fragment = urlsplit(candidate).fragment
        parsed = parse_qs(fragment, keep_blank_values=True)
        if parsed.get("c"):
            candidate = parsed["c"][0]
    if candidate.startswith("#c="):
        candidate = candidate[3:]
    if not candidate or "://" in candidate or candidate.startswith("#c="):
        raise ValueError("chat_id must be a Rubika GUID or a web link containing #c=<guid>")
    return candidate


def _unwrap_message(value: Mapping[str, Any]) -> Message:
    raw = value.get("message")
    return Message.from_dict(raw if isinstance(raw, Mapping) else value)


class MessagesService:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def send(self, chat_id: str, text: str, *, reply_to_message_id: str | None = None, wait: bool = True, timeout: float | None = 30) -> Message | QueuedOperation:
        payload = {"chat_id": normalize_chat_id(chat_id), "text": text, "reply_to_message_id": reply_to_message_id}
        result = await self._client._submit("messages.send", payload, wait=wait, timeout=timeout)
        return result if isinstance(result, QueuedOperation) else _unwrap_message(result)

    async def reply(self, chat_id: str, message_id: str, text: str, *, wait: bool = True, timeout: float | None = 30) -> Message | QueuedOperation:
        return await self.send(chat_id, text, reply_to_message_id=message_id, wait=wait, timeout=timeout)

    async def _send_media(self, chat_id: str, file_inline: Mapping[str, Any], *, caption: str | None,
                          reply_to_message_id: str | None, wait: bool, timeout: float | None) -> Message | QueuedOperation:
        payload = {'chat_id': normalize_chat_id(chat_id), 'file_inline': dict(file_inline),
                   'text': caption, 'reply_to_message_id': reply_to_message_id}
        result = await self._client._submit('messages.send', payload, wait=wait, timeout=timeout)
        return result if isinstance(result, QueuedOperation) else _unwrap_message(result)

    async def edit(self, chat_id: str, message_id: str, text: str, *, wait: bool = True, timeout: float | None = 30) -> Message | QueuedOperation:
        result = await self._client._submit("messages.edit", {"chat_id": normalize_chat_id(chat_id), "message_id": message_id, "text": text}, wait=wait, timeout=timeout)
        return result if isinstance(result, QueuedOperation) else _unwrap_message(result)

    async def delete(self, chat_id: str, message_id: str, *, wait: bool = True, timeout: float | None = 30) -> Mapping[str, Any] | QueuedOperation:
        return await self._client._submit("messages.delete", {"chat_id": normalize_chat_id(chat_id), "message_id": message_id}, wait=wait, timeout=timeout)

    async def forward(self, from_chat_id: str, message_id: str, to_chat_id: str, *, wait: bool = True, timeout: float | None = 30) -> Message | QueuedOperation:
        payload = {"from_chat_id": normalize_chat_id(from_chat_id), "message_id": message_id, "to_chat_id": normalize_chat_id(to_chat_id)}
        result = await self._client._submit("messages.forward", payload, wait=wait, timeout=timeout)
        return result if isinstance(result, QueuedOperation) else _unwrap_message(result)

    async def history(self, chat_id: str, *, cursor: str | None = None, limit: int | None = None) -> tuple[Message, ...]:
        result = await self._client._read("messages.history", {"chat_id": normalize_chat_id(chat_id), "cursor": cursor, "limit": limit})
        values = result.get("messages", [])
        if not isinstance(values, list):
            raise ValueError("The reviewed history contract returned an invalid messages collection")
        return tuple(Message.from_dict(value) for value in values if isinstance(value, Mapping))
