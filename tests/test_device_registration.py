from __future__ import annotations

import asyncio
import json

from Crypto.PublicKey import RSA
import httpx
import pytest

from fnc_rubika import Client, PassphraseKeyProvider, Session
from fnc_rubika.exceptions import AccessDeniedError, SessionRenewalError, TransportError
from fnc_rubika.rubika import RubikaCipher, RubikaTransport


AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


@pytest.mark.parametrize('stored_session', [False, True])
@pytest.mark.parametrize('version', ['5', '6'])
def test_device_registration_precedes_validation_and_send(tmp_path, stored_session, version):
    async def scenario():
        signing_key = RSA.generate(1024).export_key().decode() if version == '6' else None
        session = Session(AUTH, account_id='own-account', device_id='test-device', api_version=version, private_key=signing_key)
        login_calls = []
        class Authenticator:
            async def begin(self, phone):
                login_calls.append('begin')
                return 'challenge'
            async def complete(self, challenge, code):
                login_calls.append('complete')
                return session

        registered = False
        calls = []
        def server(request):
            nonlocal registered
            body = json.loads(request.content)
            inner = RubikaCipher(AUTH).decrypt(body['data_enc'])
            method = inner['method']
            calls.append(method)
            if method == 'registerDevice':
                assert inner['input']['device_hash'] == 'test-device'
                registered = True
                reply = {'status': 'OK', 'data': {}}
            elif not registered:
                reply = {'status': 'ERROR_ACTION', 'status_det': 'NOT_REGISTERED'}
            elif method == 'getChats':
                reply = {'status': 'OK', 'data': {'chats': []}}
            elif method == 'sendMessage':
                assert inner['input']['text'] == 'hello'
                reply = {'status': 'OK', 'data': {'message_update': {'message': {'message_id': '1', 'text': 'hello'}}}}
            else:
                raise AssertionError('Unexpected RPC: '+method)
            return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt(reply)})

        client = Client('personal', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'),
                        authenticator_factory=Authenticator, input_func=lambda _: '09123456789', otp_input_func=lambda _: '12345')
        if stored_session:
            client.store.save_secret('session', session.as_dict())

        transports = []
        def make_transport(value):
            transport = RubikaTransport(client.registry, value, http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
            transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/']}
            async def stream_events(cursor):
                await asyncio.Event().wait()
                yield {}
            transport.stream_events = stream_events
            transports.append(transport)
            return transport
        client._transport = make_transport

        async with client:
            assert calls == ['registerDevice', 'getChats']
            assert client.async_client()._started
            assert (await client.send('#c=destination', 'hello')).message_id == '1'
        assert calls == ['registerDevice', 'getChats', 'sendMessage']
        assert login_calls == ([] if stored_session else ['begin', 'complete'])
        assert len(transports) == 1
        assert transports[0]._closed
        assert (tmp_path / 'personal.rubika').is_file()
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['denied', 'offline'])
def test_registration_failure_does_not_start_reads_or_workers_or_repeat_otp(tmp_path, failure):
    async def scenario():
        login_calls = []
        class Authenticator:
            async def begin(self, phone):
                login_calls.append('begin')
                return 'challenge'
            async def complete(self, challenge, code):
                return Session(AUTH)

        client = Client('personal', data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'),
                        authenticator_factory=Authenticator, input_func=lambda _: '09123456789', otp_input_func=lambda _: '12345')
        transport = RubikaTransport(client.registry, Session(AUTH))
        calls = []
        async def rpc(method, payload):
            calls.append(method)
            if failure == 'denied':
                raise AccessDeniedError()
            raise TransportError('Offline')
        transport.rpc = rpc
        client._transport = lambda _: transport
        try:
            with pytest.raises(SessionRenewalError if failure == 'denied' else TransportError):
                await client.start()
            if failure == 'denied':
                with pytest.raises(SessionRenewalError):
                    await client.start()
            assert login_calls == ['begin']
            assert calls == ['registerDevice']
            assert not client.async_client()._started
            assert not transport._prepared
        finally:
            await client.aclose()
    asyncio.run(scenario())
