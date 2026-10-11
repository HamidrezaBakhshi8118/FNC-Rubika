"""Async client lifecycle, durable event dispatch, and persistent operations."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
import inspect
import random
from typing import Any, Protocol

from .exceptions import (
    AmbiguousDeliveryError,
    ClientClosedError,
    OperationUnknownError,
    RateLimitError,
    RemoteOperationError,
    SessionExpiredError,
    TransportError,
    ContractError,
)
from .models import Delivery, EventEnvelope, QueuedOperation, Session
from .storage import EncryptedSQLiteStore
from .transport import Transport


Handler = Callable[["AsyncClient", Delivery], Any | Awaitable[Any]]


class OtpAuthenticator(Protocol):
    """Provider-specific, reviewed OTP adapter. Implementations must not log OTP values."""

    async def begin(self, phone_number: str) -> str: ...

    async def complete(self, challenge_id: str, code: str) -> Session: ...


class AsyncClient:
    """Durable async client over an injected, contract-reviewed transport.

    ``events()`` leases persisted messages one at a time.  Acknowledge only after
    consumer side effects are complete.  ``run()`` does that automatically for
    registered handlers and can use multiple workers.
    """

    def __init__(
        self,
        transport: Transport,
        store: EncryptedSQLiteStore,
        *,
        reconnect_base_seconds: float = 0.5,
        reconnect_max_seconds: float = 30,
        event_lease_seconds: float = 60,
    ) -> None:
        self.transport = transport
        self.store = store
        self.reconnect_base_seconds = reconnect_base_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.event_lease_seconds = event_lease_seconds
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._stop = asyncio.Event()
        self._inbox_changed = asyncio.Event()
        self._outbox_changed = asyncio.Event()
        self._receiver_task: asyncio.Task[None] | None = None
        self._outbox_task: asyncio.Task[None] | None = None
        self._fatal_error: Exception | None = None
        self._closed = False
        self._started = False
        self._messages: Any | None = None
        self._media: Any | None = None
        self._api: Any | None = None

    async def __aenter__(self) -> "AsyncClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def messages(self) -> Any:
        if self._messages is None:
            from .messages import MessagesService

            self._messages = MessagesService(self)
        return self._messages

    @property
    def media(self) -> Any:
        if self._media is None:
            from .media import MediaService

            self._media = MediaService(self)
        return self._media

    @property
    def api(self) -> Any:
        """Expose every operation in the reviewed catalog through dynamic namespaces."""

        if self._api is None:
            registry = getattr(self.transport, "registry", None)
            if registry is None:
                raise ContractError("Dynamic API access requires a contract-backed transport")
            from .api import CatalogApi

            self._api = CatalogApi(self, registry)
        return self._api

    @property
    def session_expired(self) -> bool:
        return isinstance(self._fatal_error, SessionExpiredError)

    def on(self, event_type: str, handler: Handler | None = None):
        """Register a handler; ``'*'`` receives every normalized event."""

        def register(callback: Handler) -> Handler:
            self._handlers[event_type].append(callback)
            return callback

        return register if handler is None else register(handler)

    async def begin_login(self, authenticator: OtpAuthenticator, phone_number: str) -> str:
        """Start a provider-specific OTP flow without persisting or logging the OTP."""

        return await authenticator.begin(phone_number)

    async def complete_login(self, authenticator: OtpAuthenticator, challenge_id: str, code: str) -> Session:
        """Complete a provider-specific OTP flow and encrypt the resulting session."""

        session = await authenticator.complete(challenge_id, code)
        self.store.save_secret("session", session.as_dict())
        return session

    def load_session(self) -> Session | None:
        value = self.store.load_secret("session")
        return Session.from_dict(value) if value else None

    async def start(self) -> None:
        if self._closed:
            raise ClientClosedError("The client is closed")
        if self._started:
            return
        self._started = True
        self._receiver_task = asyncio.create_task(self._receive_loop(), name="fnc-rubika-receiver")
        self._outbox_task = asyncio.create_task(self._outbox_loop(), name="fnc-rubika-outbox")

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self._inbox_changed.set()
        self._outbox_changed.set()
        tasks = [task for task in (self._receiver_task, self._outbox_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.transport.aclose()

    async def _receive_loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                cursor = self.store.get_cursor()
                saw_frame = False
                async for raw_event in self.transport.stream_events(cursor):
                    saw_frame = True
                    event = self._normalize_event(raw_event)
                    if self.store.record_event(event):
                        self._inbox_changed.set()
                    if self._stop.is_set():
                        return
                if not self._stop.is_set():
                    raise TransportError("The realtime stream ended")
            except SessionExpiredError as exc:
                self._fatal_error = exc
                self._inbox_changed.set()
                self._outbox_changed.set()
                return
            except asyncio.CancelledError:
                raise
            except TransportError:
                attempt += 1
                await self._sleep_backoff(attempt)
            except Exception as exc:
                self._fatal_error = TransportError("Unexpected realtime transport failure")
                self._inbox_changed.set()
                return
            else:
                attempt = 0 if saw_frame else attempt + 1

    def _normalize_event(self, raw_event: Mapping[str, Any]) -> EventEnvelope:
        try:
            return EventEnvelope(
                event_id=str(raw_event["event_id"]),
                type=str(raw_event["type"]),
                payload=dict(raw_event.get("payload") or {}),
                cursor=str(raw_event["cursor"]) if raw_event.get("cursor") is not None else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportError("The transport produced an invalid normalized event") from exc

    async def _sleep_backoff(self, attempt: int) -> None:
        ceiling = min(self.reconnect_max_seconds, self.reconnect_base_seconds * (2 ** min(attempt, 12)))
        delay = random.uniform(ceiling / 2, ceiling)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            return

    async def _next_delivery(self) -> Delivery:
        while not self._closed:
            if self._fatal_error is not None:
                raise self._fatal_error
            event = self.store.claim_event(lease_seconds=self.event_lease_seconds)
            if event is not None:
                return Delivery(event, self._ack_delivery, self._nack_delivery)
            self._inbox_changed.clear()
            # Check after clearing to avoid missing a producer's signal.
            event = self.store.claim_event(lease_seconds=self.event_lease_seconds)
            if event is not None:
                return Delivery(event, self._ack_delivery, self._nack_delivery)
            try:
                await asyncio.wait_for(self._inbox_changed.wait(), timeout=1)
            except TimeoutError:
                pass
        raise ClientClosedError("The client is closed")

    async def events(self) -> AsyncIterator[Delivery]:
        await self.start()
        while True:
            yield await self._next_delivery()

    async def _ack_delivery(self, event_id: str, cursor: str | None) -> None:
        self.store.acknowledge_event(event_id, cursor)
        self._inbox_changed.set()

    async def _nack_delivery(self, event_id: str) -> None:
        self.store.release_event(event_id)
        self._inbox_changed.set()

    async def run(self, *, workers: int = 1) -> None:
        """Continuously dispatch registered handlers with durable acknowledgement."""

        if workers < 1:
            raise ValueError("workers must be at least 1")
        await self.start()
        tasks = [asyncio.create_task(self._event_worker(), name=f"fnc-rubika-worker-{index}") for index in range(workers)]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _event_worker(self) -> None:
        while not self._closed:
            delivery = await self._next_delivery()
            handlers = [*self._handlers.get(delivery.event.type, ()), *self._handlers.get("*", ())]
            try:
                for handler in handlers:
                    result = handler(self, delivery)
                    if inspect.isawaitable(result):
                        await result
            except asyncio.CancelledError:
                await delivery.nack()
                raise
            except Exception:
                await delivery.nack()
                await asyncio.sleep(0.1)
            else:
                await delivery.ack()

    async def _submit(self, operation: str, payload: Mapping[str, Any], *, wait: bool = True, timeout: float | None = 30) -> Mapping[str, Any] | QueuedOperation:
        await self.start()
        queued = self.store.enqueue_operation(operation, payload)
        self._outbox_changed.set()
        if not wait:
            return queued
        return await self.wait_operation(queued.operation_id, timeout=timeout)

    async def wait_operation(self, operation_id: str, *, timeout: float | None = 30) -> Mapping[str, Any]:
        async def wait_for_terminal_state() -> Mapping[str, Any]:
            while True:
                state = self.store.operation_state(operation_id)
                if state is None:
                    raise KeyError(f"Unknown operation {operation_id}")
                if state["state"] == "delivered":
                    return dict(state["result"] or {})
                if state["state"] == "failed":
                    raise RemoteOperationError((state["error"] or {}).get("message", "The operation failed"))
                if state["state"] == "unknown":
                    raise OperationUnknownError((state["error"] or {}).get("message", "Delivery outcome is unknown"))
                self._outbox_changed.clear()
                await asyncio.sleep(0.02)

        if timeout is None:
            return await wait_for_terminal_state()
        return await asyncio.wait_for(wait_for_terminal_state(), timeout=timeout)

    async def _outbox_loop(self) -> None:
        while not self._stop.is_set():
            if self.session_expired:
                # Keep queued work encrypted and durable, but never send it with a rejected session.
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=0.25)
                except TimeoutError:
                    pass
                continue
            operation = self.store.claim_operation()
            if operation is None:
                self._outbox_changed.clear()
                try:
                    await asyncio.wait_for(self._outbox_changed.wait(), timeout=0.25)
                except TimeoutError:
                    pass
                continue
            operation_id = str(operation["operation_id"])
            try:
                result = await self.transport.request(
                    str(operation["operation"]),
                    operation["payload"],
                    idempotency_key=str(operation["idempotency_key"]),
                )
            except SessionExpiredError as exc:
                self.store.fail_operation(operation_id, error=str(exc))
                self._fatal_error = exc
            except RateLimitError as exc:
                self.store.retry_operation(operation_id, delay_seconds=exc.retry_after or self._retry_delay(operation), error=str(exc))
            except AmbiguousDeliveryError as exc:
                if self._supports_idempotency(str(operation["operation"])):
                    self.store.retry_operation(operation_id, delay_seconds=self._retry_delay(operation), error=str(exc))
                else:
                    self.store.fail_operation(operation_id, error=str(exc), unknown=True)
            except RemoteOperationError as exc:
                self.store.fail_operation(operation_id, error=str(exc))
            except TransportError as exc:
                self.store.retry_operation(operation_id, delay_seconds=self._retry_delay(operation), error=str(exc))
            except asyncio.CancelledError:
                self.store.retry_operation(operation_id, delay_seconds=0, error="Client stopped during operation")
                raise
            except Exception:
                self.store.retry_operation(operation_id, delay_seconds=self._retry_delay(operation), error="Unexpected transport failure")
            else:
                self.store.complete_operation(operation_id, result)
            finally:
                self._outbox_changed.set()

    def _supports_idempotency(self, operation: str) -> bool:
        predicate = getattr(self.transport, "supports_idempotency", None)
        return bool(predicate(operation)) if callable(predicate) else False

    @staticmethod
    def _retry_delay(operation: Mapping[str, Any]) -> float:
        attempts = int(operation.get("attempts", 1))
        return min(30.0, 0.5 * (2 ** min(attempts - 1, 6))) * random.uniform(0.5, 1.0)

    async def _read(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        await self.start()
        # Read endpoints should have no side effects; the random key is ignored unless their contract opts in.
        from uuid import uuid4

        return await self.transport.request(operation, payload, idempotency_key=str(uuid4()))
