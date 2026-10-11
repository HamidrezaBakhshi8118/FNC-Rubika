from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from fnc_rubika import Client, EncryptedSQLiteStore, PassphraseKeyProvider, Session
from fnc_rubika.client import AsyncClient
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.exceptions import InvalidCodeError, SessionExpiredError, TwoStepRequiredError
from fnc_rubika.exceptions import SecurityConfigurationError


class Transport:
    def __init__(self, reject=False):
        self.reject = reject
        self.closed = False
        self.request_count = 0
    async def request(self, operation, payload, *, idempotency_key):
        self.request_count += 1
        if self.reject:
            await asyncio.sleep(0)
            raise SessionExpiredError('Session rejected')
        return {'message': {'chat_id': 'chat', 'message_id': '1', 'text': 'ok'}}
    async def stream_events(self, cursor):
        if self.reject:
            raise SessionExpiredError('Realtime session rejected')
        await asyncio.sleep(3600)
        yield {}
    async def aclose(self):
        self.closed = True


def test_simultaneous_requests_and_receiver_renew_once_and_preserve_outbox(tmp_path):
    async def scenario():
        old, new = Transport(True), Transport()
        calls = []
        async def renew():
            calls.append(True)
            await asyncio.sleep(.03)
            return new
        store = EncryptedSQLiteStore(tmp_path/'state.db', key_provider=PassphraseKeyProvider('long test passphrase'))
        client = AsyncClient(old, store, reauthenticate=renew)
        handler = lambda *_: None
        client.on('message', handler)
        try:
            first, second, mutation = await asyncio.wait_for(asyncio.gather(client._read('read', {}), client._read('read', {}), client.messages.send('chat', 'ok')), 2)
            assert first == second
            assert mutation.message_id == '1'
            assert calls == [True]
            assert client._handlers['message'] == [handler]
            assert old.closed
            assert not client.session_expired
        finally:
            await client.aclose()
            store.close()
    asyncio.run(scenario())


def test_disabled_auto_login_raises_without_terminal_prompt(tmp_path):
    async def scenario():
        client = Client('no-prompt', data_dir=tmp_path, auto_login=False, key_provider=PassphraseKeyProvider('long test passphrase'))
        try:
            with pytest.raises(SessionExpiredError):
                await client.start()
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_expired_stored_session_prompts_and_keeps_prelogin_handler(tmp_path):
    class Auth:
        async def begin(self, phone):
            assert phone == '+989123456789'
            return 'challenge'
        async def complete(self, challenge, code):
            assert code == '12345'
            return Session('new-session')
        async def aclose(self):
            pass
    async def scenario():
        catalog = ContractRegistry.from_mapping({'version': 'test', 'base_url': 'https://example.invalid', 'endpoints': []})
        prompts = []
        def phone(prompt):
            prompts.append(prompt)
            return '09123456789'
        def code(prompt):
            prompts.append(prompt)
            return '۱۲۳۴۵'
        client = Client('expired', registry=catalog, data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'),
                        authenticator_factory=Auth, input_func=phone, otp_input_func=code)
        client._transport = lambda _: Transport()
        client.store.save_secret('session', Session('old', expires_at=datetime.now(timezone.utc)-timedelta(days=1)).as_dict())
        @client.on('message')
        async def handler(*_):
            pass
        async with client:
            assert len(prompts) == 2
            assert client.async_client()._handlers['message'] == [handler]
            assert client.store.load_secret('session')['access_token'] == 'new-session'
    asyncio.run(scenario())


def test_two_step_password_and_invalid_otp_retry_are_hidden(tmp_path):
    class Auth:
        async def begin(self, phone):
            raise TwoStepRequiredError()
        async def begin_with_password(self, phone, password):
            assert password == 'existing-password'
            return 'challenge'
        async def complete(self, challenge, code):
            if code == '00000':
                raise InvalidCodeError()
            return Session('new-session')
    async def scenario():
        client = Client('two-step', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'))
        values = iter(['existing-password', '00000', '12345'])
        try:
            await client.login_interactive(input_func=lambda _: '09123456789', otp_input_func=lambda _: next(values), authenticator=Auth())
            assert client.has_session()
        finally:
            await client.aclose()
    asyncio.run(scenario())


def test_account_switch_cannot_reuse_previous_account_queue(tmp_path):
    async def scenario():
        client = Client('account', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'))
        client.store.save_secret('session', Session('old', account_id='first').as_dict())
        try:
            with pytest.raises(SecurityConfigurationError):
                await client._save_session(Session('new', account_id='second'))
            assert client.store.load_secret('session')['account_id'] == 'first'
        finally:
            await client.aclose()
    asyncio.run(scenario())
