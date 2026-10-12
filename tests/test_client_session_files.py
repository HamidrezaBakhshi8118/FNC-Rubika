from __future__ import annotations

import asyncio
from pathlib import Path
from typing import get_type_hints

import pytest

from fnc_rubika import Client, PassphraseKeyProvider, Session, SyncClient
from fnc_rubika.auth import default_catalog_path
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.exceptions import AccessDeniedError, SessionExpiredError, SessionRenewalError, TransportError
from fnc_rubika.messages import MessagesService
from fnc_rubika.rubika import RubikaTransport


class Transport:
    def __init__(self, registry, *, denied=False, unavailable=False):
        self.registry = registry
        self.denied = denied
        self.unavailable = unavailable
        self.closed = False
        self.calls = []
        self.validations = 0

    async def validate_session(self):
        self.validations += 1
        if self.unavailable:
            raise TransportError('Connection unavailable')
        if self.denied:
            raise SessionExpiredError('Account checks rejected')

    async def request(self, operation, payload, *, idempotency_key):
        self.calls.append((operation, dict(payload)))
        if operation == 'messages.send':
            return {'message': {'chat_id': payload['chat_id'], 'message_id': '1', 'text': payload['text']}}
        return {'chats': []}

    async def stream_events(self, cursor):
        await asyncio.Event().wait()
        yield {}

    async def aclose(self):
        self.closed = True


class Auth:
    def __init__(self):
        self.logins = 0

    async def begin(self, phone):
        self.logins += 1
        return 'challenge'

    async def complete(self, challenge, code):
        return Session('new-session', account_id='account')


def named(tmp_path, auth=None):
    auth = auth or Auth()
    prompts = []
    def phone(prompt):
        prompts.append(prompt)
        return '09123456789'
    def code(prompt):
        prompts.append(prompt)
        return '12345'
    client = Client('personal', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'),
                    authenticator_factory=lambda: auth, input_func=phone, otp_input_func=code)
    return client, auth, prompts


def test_default_session_is_local_rubika_and_old_appdata_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'old-location'))
    client = Client('personal', key_provider=PassphraseKeyProvider('long test passphrase'))
    try:
        assert client.session_path == tmp_path / 'personal.rubika'
        assert client.session_path.is_file()
        assert not client.has_session()
        assert not (tmp_path / 'old-location').exists()
    finally:
        asyncio.run(client.aclose())


def test_name_with_rubika_extension_reopens_the_same_store(tmp_path):
    async def scenario():
        first, _, _ = named(tmp_path)
        first.store.save_secret('session', Session('existing').as_dict())
        await first.aclose()
        second = Client('personal.rubika', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'))
        try:
            assert second.session_path == tmp_path / 'personal.rubika'
            assert second.has_session()
        finally:
            await second.aclose()
    asyncio.run(scenario())


def test_missing_session_logs_in_direct_send_and_reopens_without_prompt(tmp_path):
    async def scenario():
        client, auth, prompts = named(tmp_path)
        transport = Transport(client.registry)
        client._transport = lambda _: transport
        try:
            result = await client.send('#c=user', 'hello')
            assert result.message_id == '1'
            assert auth.logins == 1
            assert len(prompts) == 2
            assert transport.calls == [('messages.send', {'chat_id': 'user', 'text': 'hello', 'reply_to_message_id': None})]
        finally:
            await client.aclose()
        assert b'new-session' not in (tmp_path / 'personal.rubika').read_bytes()
        reopened, second_auth, second_prompts = named(tmp_path)
        reopened._transport = lambda _: Transport(reopened.registry)
        async with reopened:
            assert reopened.has_session()
            assert second_auth.logins == 0
            assert second_prompts == []
    asyncio.run(scenario())


@pytest.mark.parametrize('replacement_denied', [False, True])
def test_rejected_stored_session_prompts_once_before_workers_or_send(tmp_path, replacement_denied):
    async def scenario():
        client, auth, prompts = named(tmp_path)
        old = Transport(client.registry, denied=True)
        new = Transport(client.registry, denied=replacement_denied)
        client.store.save_secret('session', Session('old-session', account_id='account').as_dict())
        client._transport = lambda session: old if session.access_token == 'old-session' else new
        try:
            if replacement_denied:
                for _ in range(2):
                    with pytest.raises(SessionRenewalError, match='automatic login will not repeat'):
                        await client.start()
                assert not client.async_client()._started
            else:
                await client.start()
                await client.start()
                assert client.async_client()._started
            assert old.closed
            assert auth.logins == 1
            assert len(prompts) == 2
            assert old.calls == new.calls == []
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_fresh_rejected_session_does_not_request_another_code(tmp_path):
    async def scenario():
        client, auth, prompts = named(tmp_path)
        client._transport = lambda _: Transport(client.registry, denied=True)
        try:
            with pytest.raises(SessionRenewalError):
                await client.start()
            with pytest.raises(SessionRenewalError):
                await client.start()
            assert auth.logins == 1
            assert len(prompts) == 2
        finally:
            await client.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('auto_login,unavailable', [(False, False), (True, True)])
def test_unattended_or_network_failure_does_not_prompt(tmp_path, auto_login, unavailable):
    async def scenario():
        client, auth, prompts = named(tmp_path)
        client.auto_login = auto_login
        client.store.save_secret('session', Session('old-session').as_dict())
        client._transport = lambda _: Transport(client.registry, denied=True, unavailable=unavailable)
        try:
            with pytest.raises(TransportError if unavailable else SessionExpiredError):
                await client.start()
            assert auth.logins == 0
            assert prompts == []
        finally:
            await client.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('results,expected', [
    ([AccessDeniedError(), AccessDeniedError()], SessionExpiredError),
    ([AccessDeniedError(), {}], None),
    ([{}], None),
    ([TransportError('Offline')], TransportError),
])
def test_native_validation_uses_account_reads_and_preserves_network_errors(results, expected):
    async def scenario():
        transport = RubikaTransport(ContractRegistry.from_file(default_catalog_path()), Session('a'*32, account_id='own-account'))
        calls = []
        async def rpc(operation, payload):
            calls.append((operation, payload))
            result = results[len(calls)-1]
            if isinstance(result, Exception):
                raise result
            return result
        transport.rpc = rpc
        try:
            if expected:
                with pytest.raises(expected):
                    await transport.validate_session()
            else:
                await transport.validate_session()
            assert calls[0] == ('getChats', {})
            if len(calls) == 2:
                assert calls[1] == ('getUserInfo', {'user_guid': 'own-account'})
        finally:
            await transport.aclose()
    asyncio.run(scenario())


def test_native_methods_are_real_typed_members_and_wait_flags_stay_local(tmp_path):
    registry = ContractRegistry.from_file(default_catalog_path())
    for name in registry.operations():
        if name.isidentifier():
            assert callable(getattr(Client, name))
            assert callable(getattr(SyncClient, name))
    assert get_type_hints(Client.messages.fget)['return'] is MessagesService
    assert get_type_hints(Client.send)['return'] is not object
    assert Path(__import__('fnc_rubika').__file__).with_name('py.typed').is_file()
    async def scenario():
        client, _, _ = named(tmp_path)
        transport = Transport(client.registry)
        client._transport = lambda _: transport
        try:
            assert await client.getChats(wait=False, timeout=.5, marker='local') == {'chats': []}
            assert transport.calls == [('getChats', {'marker': 'local'})]
        finally:
            await client.aclose()
    asyncio.run(scenario())
