from __future__ import annotations

import asyncio

import pytest

from fnc_rubika import Client, EncryptedSQLiteStore, PassphraseKeyProvider, Session, SessionPool
from fnc_rubika.client import AsyncClient
from fnc_rubika.contracts import ContractRegistry


class FakeTransport:
    async def request(self, operation, payload, *, idempotency_key):
        del operation, payload, idempotency_key
        return {}

    async def stream_events(self, cursor):
        del cursor
        await asyncio.sleep(3600)
        if False:
            yield {}

    async def download(self, file_id, destination):
        del file_id, destination
        return {}

    async def aclose(self):
        return None


def test_named_client_supports_direct_async_with(tmp_path):
    async def scenario() -> None:
        registry = ContractRegistry.from_mapping({"version": "test", "base_url": "https://example.invalid", "endpoints": []})
        named = Client("personal", registry=registry, data_dir=tmp_path, key_provider=PassphraseKeyProvider("a long test passphrase"))
        named._client = AsyncClient(  # type: ignore[attr-defined]  # Injected test transport.
            FakeTransport(),
            named.store,
        )
        named.store.save_secret("session", Session("test-token").as_dict())
        async with named as client:
            assert client.session_name == "personal"
            assert client.messages is not None

    asyncio.run(scenario())


def test_named_client_interactively_creates_a_missing_session_before_start(tmp_path):
    async def scenario() -> None:
        registry = ContractRegistry.from_mapping({"version": "test", "base_url": "https://example.invalid", "endpoints": []})
        named = Client("new-account", registry=registry, data_dir=tmp_path, key_provider=PassphraseKeyProvider("a long test passphrase"))
        seen: list[bool] = []

        async def fake_interactive_login() -> Session:
            seen.append(True)
            session = Session("test-token")
            named.store.save_secret("session", session.as_dict())
            named._client = AsyncClient(FakeTransport(), named.store)  # type: ignore[attr-defined]
            return session

        named.login_interactive = fake_interactive_login  # type: ignore[method-assign]
        async with named:
            assert named.has_session()
        assert seen == [True]

    asyncio.run(scenario())


def test_session_pool_rejects_duplicate_names():
    with pytest.raises(ValueError, match="unique"):
        SessionPool("personal", "personal")
