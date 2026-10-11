from __future__ import annotations

import asyncio
import json

import websockets

from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.models import Session
from fnc_rubika.transport import HttpWebSocketTransport


def test_websocket_heartbeat_and_normalized_frame():
    async def scenario() -> None:
        heartbeat_seen = asyncio.Event()

        async def handler(connection):
            raw = await connection.recv()
            assert json.loads(raw) == {"kind": "heartbeat"}
            heartbeat_seen.set()
            await connection.send(json.dumps({"id": "event-1", "kind": "message", "body": {"text": "hello"}, "cursor": "c1"}))

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            registry = ContractRegistry.from_mapping(
                {
                    "version": "test-v1",
                    "base_url": "https://example.invalid",
                    "endpoints": [],
                    "websocket": {
                        "url": f"ws://127.0.0.1:{port}",
                        "event_id_field": "id",
                        "event_type_field": "kind",
                        "payload_field": "body",
                        "cursor_field": "cursor",
                        "heartbeat_seconds": 0.01,
                        "heartbeat_payload": {"kind": "heartbeat"},
                    },
                }
            )
            transport = HttpWebSocketTransport(registry, Session("test-token"))
            try:
                event = await asyncio.wait_for(anext(transport.stream_events(None)), timeout=1)
            finally:
                await transport.aclose()
            assert event == {"event_id": "event-1", "type": "message", "payload": {"text": "hello"}, "cursor": "c1"}
            assert heartbeat_seen.is_set()

    asyncio.run(scenario())
