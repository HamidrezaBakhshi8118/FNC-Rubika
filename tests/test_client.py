from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Mapping

import pytest

from fnc_rubika import AsyncClient, EncryptedSQLiteStore, PassphraseKeyProvider, SyncClient
from fnc_rubika.exceptions import AccessDeniedError, RateLimitError, TransportError


class FakeTransport:
    def __init__(self, events: list[Mapping[str, Any]] | None = None, *, rate_limit_once: bool = False) -> None:
        self.events = list(events or [])
        self.requests: list[tuple[str, Mapping[str, Any], str]] = []
        self.rate_limit_once = rate_limit_once
        self.closed = False

    def supports_idempotency(self, _: str) -> bool:
        return True

    async def request(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str) -> Mapping[str, Any]:
        self.requests.append((operation, payload, idempotency_key))
        if self.rate_limit_once:
            self.rate_limit_once = False
            raise RateLimitError(0.01)
        if operation == "messages.history":
            return {"messages": [{"chat_id": "c", "message_id": "old", "text": "history"}]}
        return {"message": {"chat_id": payload.get("chat_id", "c"), "message_id": "m-1", "text": payload.get("text")}}

    async def stream_events(self, cursor: str | None):
        del cursor
        for event in self.events:
            yield event
        await asyncio.sleep(3600)
        if False:
            yield {}

    async def download(self, file_id: str, destination: Path) -> Mapping[str, Any]:
        destination.write_bytes(b"media")
        return {"file_id": file_id, "path": str(destination), "size": 5}

    async def aclose(self) -> None:
        self.closed = True


def make_client(tmp_path, transport: FakeTransport) -> AsyncClient:
    store = EncryptedSQLiteStore(tmp_path / "state.sqlite3", key_provider=PassphraseKeyProvider("a long test passphrase"))
    return AsyncClient(transport, store, reconnect_base_seconds=0.01, reconnect_max_seconds=0.02)


def test_message_send_retries_rate_limit_and_is_durable(tmp_path):
    async def scenario() -> None:
        transport = FakeTransport(rate_limit_once=True)
        async with make_client(tmp_path, transport) as client:
            message = await client.messages.send("chat-1", "hello", timeout=2)
            assert message.message_id == "m-1"
            assert len(transport.requests) == 2

    asyncio.run(scenario())


def test_access_denial_survives_outbox_and_store_reopen_without_login_or_retry(tmp_path):
    class DeniedTransport(FakeTransport):
        async def request(self, operation, payload, *, idempotency_key):
            self.requests.append((operation, payload, idempotency_key))
            raise AccessDeniedError()

    async def scenario():
        transport = DeniedTransport()
        client = make_client(tmp_path, transport)

        async def unexpected_login():
            pytest.fail('Access denial must not request a new session')

        client._reauthenticate = unexpected_login
        try:
            async with client:
                queued = await client.messages.send('chat-1', 'hello', wait=False)
                with pytest.raises(AccessDeniedError, match='destination GUID'):
                    await client.wait_operation(queued.operation_id, timeout=2)
                assert len(transport.requests) == 1
                assert not client.session_expired
                assert client.store.operation_state(queued.operation_id)['state'] == 'failed'
        finally:
            client.store.close()

        reopened = make_client(tmp_path, FakeTransport())
        try:
            with pytest.raises(AccessDeniedError) as rejected:
                await reopened.wait_operation(queued.operation_id, timeout=2)
            assert rejected.value.status == 'ERROR_GENERIC'
            assert rejected.value.status_det == 'INVALID_AUTH'
        finally:
            await reopened.aclose()
            reopened.store.close()
    asyncio.run(scenario())


def test_event_delivery_is_deduplicated_and_cursor_advances_on_ack(tmp_path):
    async def scenario() -> None:
        event = {"event_id": "e-1", "type": "message", "payload": {"text": "hello"}, "cursor": "c-1"}
        transport = FakeTransport([event, event])
        async with make_client(tmp_path, transport) as client:
            iterator = client.events()
            delivery = await asyncio.wait_for(anext(iterator), timeout=1)
            assert delivery.event.payload["text"] == "hello"
            await delivery.ack()
            await asyncio.sleep(0.02)
            assert client.store.get_cursor() == "c-1"
            assert client.store.claim_event() is None

    asyncio.run(scenario())


def test_handler_run_acks_after_success(tmp_path):
    async def scenario() -> None:
        transport = FakeTransport([{"event_id": "e-2", "type": "message", "payload": {}, "cursor": "c-2"}])
        client = make_client(tmp_path, transport)
        seen: list[str] = []

        @client.on("message")
        async def handle(_, delivery):
            seen.append(delivery.event.event_id)
            await client.aclose()

        await client.run()
        assert seen == ["e-2"]
        assert client.store.get_cursor() == "c-2"

    asyncio.run(scenario())


def test_receiver_reconnects_after_a_transport_failure(tmp_path):
    class FlakyTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.connections = 0

        async def stream_events(self, cursor):
            del cursor
            self.connections += 1
            if self.connections == 1:
                raise TransportError("simulated disconnect")
            yield {"event_id": "recovered", "type": "message", "payload": {}, "cursor": "cursor"}
            await asyncio.sleep(3600)
            if False:
                yield {}

    async def scenario() -> None:
        transport = FlakyTransport()
        async with make_client(tmp_path, transport) as client:
            delivery = await asyncio.wait_for(anext(client.events()), timeout=1)
            assert delivery.event.event_id == "recovered"
            assert transport.connections >= 2

    asyncio.run(scenario())


def test_sync_facade_uses_a_private_event_loop(tmp_path):
    transport = FakeTransport()
    client = make_client(tmp_path, transport)
    with SyncClient(client) as sync_client:
        message = sync_client.messages.send("chat-1", "hello")
    assert message.message_id == "m-1"
