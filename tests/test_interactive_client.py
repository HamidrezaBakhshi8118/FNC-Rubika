from __future__ import annotations

import asyncio

import pytest

from fnc_rubika import Client, EncryptedSQLiteStore, PassphraseKeyProvider, Session, validate_iranian_phone
from fnc_rubika.client import AsyncClient
from fnc_rubika.contracts import ContractRegistry


class FakeAuthenticator:
    async def begin(self, phone_number: str) -> str:
        assert phone_number == "+989123456789"
        return "challenge"

    async def complete(self, challenge_id: str, code: str) -> Session:
        assert challenge_id == "challenge"
        assert code == "12345"
        return Session("session-token", device_id="device")


class CatalogTransport:
    def __init__(self, registry: ContractRegistry) -> None:
        self.registry = registry

    async def request(self, operation, payload, *, idempotency_key):
        del idempotency_key
        return {"operation": operation, "chat_id": payload["chat_id"]}

    async def stream_events(self, cursor):
        del cursor
        await asyncio.sleep(3600)
        if False:
            yield {}

    async def download(self, file_id, destination):
        return {"file_id": file_id, "path": str(destination)}

    async def aclose(self):
        return None


def test_iranian_phone_format_is_unambiguous():
    assert validate_iranian_phone("+98 912-345-6789") == "+989123456789"
    assert validate_iranian_phone("09123456789") == "+989123456789"
    assert validate_iranian_phone("۰۹۱۲۳۴۵۶۷۸۹") == "+989123456789"
    with pytest.raises(ValueError):
        validate_iranian_phone("0912")


def test_named_client_creates_an_encrypted_session_without_user_hardcoding(tmp_path):
    async def scenario() -> None:
        registry = ContractRegistry.from_mapping({"version": "test", "base_url": "https://example.invalid", "endpoints": []})
        client = Client(
            "personal",
            registry=registry,
            data_dir=tmp_path,
            key_provider=PassphraseKeyProvider("a long test passphrase"),
        )
        session = await client.login("+989123456789", "12345", authenticator=FakeAuthenticator())
        assert session.device_id == "device"
        assert client.has_session()
        assert b"session-token" not in (tmp_path / "personal.sqlite3").read_bytes()
        await client.aclose()

    asyncio.run(scenario())


def test_interactive_login_reads_phone_and_otp_without_source_values(tmp_path):
    async def scenario() -> None:
        registry = ContractRegistry.from_mapping({"version": "test", "base_url": "https://example.invalid", "endpoints": []})
        client = Client(
            "interactive",
            registry=registry,
            data_dir=tmp_path,
            key_provider=PassphraseKeyProvider("a long test passphrase"),
        )
        prompts: list[str] = []

        def read_phone(prompt: str) -> str:
            prompts.append(prompt)
            return "+989123456789"

        def read_otp(prompt: str) -> str:
            prompts.append(prompt)
            return "12345"

        try:
            session = await client.login_interactive(
                input_func=read_phone,
                otp_input_func=read_otp,
                authenticator=FakeAuthenticator(),
            )
            assert session.access_token == "session-token"
            assert client.has_session()
            assert len(prompts) == 2
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_catalog_api_exposes_all_reviewed_operations(tmp_path):
    async def scenario() -> None:
        registry = ContractRegistry.from_mapping(
            {
                "version": "test",
                "base_url": "https://example.invalid",
                "endpoints": [{"operation": "chats.get_info", "method": "POST", "path": "/x", "operation_kind": "read"}],
            }
        )
        store = EncryptedSQLiteStore(tmp_path / "state.sqlite3", key_provider=PassphraseKeyProvider("a long test passphrase"))
        client = AsyncClient(CatalogTransport(registry), store)
        try:
            result = await client.api.chats.get_info(chat_id="chat-1")
            assert result == {"operation": "chats.get_info", "chat_id": "chat-1"}
        finally:
            await client.aclose()

    asyncio.run(scenario())
