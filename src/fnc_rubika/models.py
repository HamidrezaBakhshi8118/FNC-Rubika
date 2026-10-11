"""Small immutable public models used by the stable v1 surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Session:
    """Authenticated session material kept encrypted by the configured store."""

    access_token: str = field(repr=False)
    device_id: str | None = None
    expires_at: datetime | None = None
    private_key: str | None = field(default=None, repr=False)
    api_version: str = "5"
    account_id: str | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= utcnow()

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "device_id": self.device_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "private_key": self.private_key,
            "api_version": self.api_version,
            "account_id": self.account_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Session":
        expires_at = value.get("expires_at")
        return cls(
            access_token=str(value["access_token"]),
            device_id=value.get("device_id"),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            private_key=value.get("private_key"),
            api_version=str(value.get("api_version", "5")),
            account_id=value.get("account_id"),
        )


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """A normalized provider event retained until a consumer acknowledges it."""

    event_id: str
    type: str
    payload: Mapping[str, Any]
    cursor: str | None = None
    received_at: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "payload": dict(self.payload),
            "cursor": self.cursor,
            "received_at": self.received_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EventEnvelope":
        received_at = value.get("received_at")
        return cls(
            event_id=str(value["event_id"]),
            type=str(value["type"]),
            payload=dict(value.get("payload") or {}),
            cursor=value.get("cursor"),
            received_at=datetime.fromisoformat(received_at) if received_at else utcnow(),
        )


AckCallback = Callable[[str, str | None], Awaitable[None]]
NackCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class Delivery:
    """An event leased to a consumer. Call ``ack`` only after side effects succeed."""

    event: EventEnvelope
    _ack: AckCallback = field(repr=False)
    _nack: NackCallback = field(repr=False)
    _settled: bool = field(default=False, init=False, repr=False)

    async def ack(self) -> None:
        if not self._settled:
            await self._ack(self.event.event_id, self.event.cursor)
            self._settled = True

    async def nack(self) -> None:
        if not self._settled:
            await self._nack(self.event.event_id)
            self._settled = True


@dataclass(frozen=True, slots=True)
class Message:
    chat_id: str
    message_id: str
    text: str | None = None
    reply_to_message_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Message":
        return cls(
            chat_id=str(value["chat_id"]),
            message_id=str(value["message_id"]),
            text=value.get("text"),
            reply_to_message_id=value.get("reply_to_message_id"),
            raw=dict(value),
        )


@dataclass(frozen=True, slots=True)
class MediaRef:
    file_id: str
    name: str | None = None
    content_type: str | None = None
    size: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaRef":
        return cls(
            file_id=str(value["file_id"]),
            name=value.get("name"),
            content_type=value.get("content_type"),
            size=int(value["size"]) if value.get("size") is not None else None,
            raw=dict(value),
        )


@dataclass(frozen=True, slots=True)
class QueuedOperation:
    operation_id: str
    operation: str
    idempotency_key: str
