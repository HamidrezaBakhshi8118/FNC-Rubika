from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from fnc_rubika import AsyncClient, EncryptedSQLiteStore, PassphraseKeyProvider, Session, SyncClient
from fnc_rubika.auth import default_catalog_path
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.exceptions import (AmbiguousDeliveryError, InvalidCodeError, OperationUnknownError,
                                   SessionExpiredError, SessionRenewalError, TransportError)
from fnc_rubika.rubika import RubikaCipher, RubikaTransport
from fnc_rubika.transport import HttpWebSocketTransport


AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


class WaitingTransport:
    def __init__(self, *, idempotent=False, unexpected_failure=False):
        self.idempotent = idempotent
        self.unexpected_failure = unexpected_failure
        self.entered = asyncio.Event()
        self.calls = []

    def supports_idempotency(self, operation):
        return self.idempotent

    async def request(self, operation, payload, *, idempotency_key):
        self.calls.append((operation, dict(payload)))
        self.entered.set()
        if self.unexpected_failure:
            raise RuntimeError('secret response body')
        await asyncio.Event().wait()

    async def stream_events(self, cursor):
        await asyncio.Event().wait()
        yield {}

    async def aclose(self):
        pass


def store(tmp_path):
    return EncryptedSQLiteStore(tmp_path/'state.db', key_provider=PassphraseKeyProvider('long test passphrase'))


@pytest.mark.parametrize('idempotent', [False, True])
def test_closing_during_delivery_does_not_replay_unconfirmed_mutation(tmp_path, idempotent):
    async def scenario():
        transport = WaitingTransport(idempotent=idempotent)
        state = store(tmp_path)
        client = AsyncClient(transport, state)
        try:
            queued = await client.messages.send('chat', 'hello', wait=False)
            await asyncio.wait_for(transport.entered.wait(), 1)
            await client.aclose()
            assert state.operation_state(queued.operation_id)['state'] == ('queued' if idempotent else 'unknown')
        finally:
            await client.aclose()
            state.close()
        reopened = store(tmp_path)
        try:
            claimed = reopened.claim_operation()
            assert (claimed is not None) == idempotent
        finally:
            reopened.close()
    asyncio.run(scenario())


def test_unexpected_failure_after_delivery_is_unknown_and_hides_response(tmp_path):
    async def scenario():
        transport = WaitingTransport(unexpected_failure=True)
        state = store(tmp_path)
        client = AsyncClient(transport, state)
        try:
            queued = await client.messages.send('chat', 'hello', wait=False)
            with pytest.raises(OperationUnknownError) as rejected:
                await client.wait_operation(queued.operation_id, timeout=1)
            assert 'secret response body' not in str(rejected.value)
            assert len(transport.calls) == 1
        finally:
            await client.aclose()
            state.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['server_error', 'non_json', 'non_object', 'bad_cipher', 'missing_data', 'missing_message_id', 'bad_message_shape'])
def test_native_malformed_response_cannot_cause_duplicate_send(tmp_path, kind):
    async def scenario():
        calls = []

        def server(request):
            calls.append(json.loads(request.content))
            if kind == 'server_error':
                return httpx.Response(503, text='unavailable')
            if kind == 'non_json':
                return httpx.Response(200, text='invalid body')
            if kind == 'non_object':
                return httpx.Response(200, json=[])
            if kind == 'bad_cipher':
                return httpx.Response(200, json={'data_enc': 'invalid'})
            data = {} if kind == 'missing_message_id' else {'message_update': 'invalid shape'}
            response = {'status': 'OK'} if kind == 'missing_data' else {'status': 'OK', 'data': data}
            return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt(response)})

        registry = ContractRegistry.from_file(default_catalog_path())
        transport = RubikaTransport(registry, Session(AUTH), http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/']}
        transport._prepared = True
        # No live WebSocket or authentication requests in this regression test.
        transport.stream_events = WaitingTransport().stream_events
        state = store(tmp_path)
        client = AsyncClient(transport, state)
        try:
            queued = await client.messages.send('chat', 'hello', wait=False)
            with pytest.raises(OperationUnknownError):
                await client.wait_operation(queued.operation_id, timeout=1)
            assert len(calls) == 1
            assert state.operation_state(queued.operation_id)['state'] == 'unknown'
        finally:
            await client.aclose()
            state.close()
    asyncio.run(scenario())


def test_native_connect_failure_is_still_retryable():
    async def scenario():
        def server(request):
            raise httpx.ConnectError('connection refused', request=request)
        registry = ContractRegistry.from_file(default_catalog_path())
        transport = RubikaTransport(registry, Session(AUTH), http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/']}
        try:
            with pytest.raises(TransportError) as rejected:
                await transport.request('messages.send', {'chat_id': 'chat', 'text': 'hello'}, idempotency_key='one')
            assert not isinstance(rejected.value, AmbiguousDeliveryError)
        finally:
            await transport.aclose()
    asyncio.run(scenario())


def test_generic_malformed_response_has_unconfirmed_delivery():
    async def scenario():
        registry = ContractRegistry.from_mapping({'version': 'test', 'base_url': 'https://example.invalid',
            'endpoints': [{'operation': 'send', 'method': 'POST', 'path': '/'}]})
        transport = HttpWebSocketTransport(registry, Session('token'))
        await transport._http.aclose()
        transport._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text='broken')))
        try:
            with pytest.raises(AmbiguousDeliveryError):
                await transport.request('send', {}, idempotency_key='one')
        finally:
            await transport.aclose()
    asyncio.run(scenario())


def test_sync_direct_method_keeps_wait_and_timeout_out_of_payload(tmp_path):
    class CatalogTransport(WaitingTransport):
        registry = ContractRegistry.from_mapping({'version': 'test', 'base_url': 'https://example.invalid',
            'endpoints': [{'operation': 'getChats', 'method': 'POST', 'path': '/'}]})
        async def request(self, operation, payload, *, idempotency_key):
            self.calls.append((operation, dict(payload)))
            return {'chats': []}

    transport = CatalogTransport()
    state = store(tmp_path)
    try:
        with SyncClient(AsyncClient(transport, state)) as client:
            assert client.getChats(wait=False, timeout=0.5, marker='one') == {'chats': []}
        assert transport.calls == [('getChats', {'marker': 'one'})]
    finally:
        state.close()


@pytest.mark.parametrize('failure_kind', ['invalid_code', 'input_ended'])
def test_concurrent_failed_renewal_reports_reason_and_does_not_prompt_again(tmp_path, failure_kind):
    class RejectedTransport(WaitingTransport):
        async def request(self, operation, payload, *, idempotency_key):
            await asyncio.sleep(0)
            raise SessionExpiredError('Session rejected')

    async def scenario():
        state = store(tmp_path)
        calls = []
        async def renew():
            calls.append(True)
            await asyncio.sleep(0)
            if failure_kind == 'invalid_code':
                raise InvalidCodeError('secret code or body')
            raise EOFError('secret terminal content')
        client = AsyncClient(RejectedTransport(), state, reauthenticate=renew)
        try:
            results = await asyncio.gather(client._read('getChats', {}), client._read('getChats', {}), return_exceptions=True)
            assert calls == [True]
            assert all(isinstance(error, SessionRenewalError) for error in results)
            assert all('secret' not in str(error) for error in results)
            expected = 'verification code' if failure_kind == 'invalid_code' else 'Terminal input ended'
            assert expected in str(results[0])
            with pytest.raises(SessionRenewalError):
                await client._read('getChats', {})
            assert calls == [True]
        finally:
            await client.aclose()
            state.close()
    asyncio.run(scenario())


def test_rejected_replacement_cannot_start_an_unbounded_login_loop(tmp_path):
    class RejectedTransport(WaitingTransport):
        async def request(self, operation, payload, *, idempotency_key):
            self.calls.append(operation)
            raise SessionExpiredError('Session rejected')

    async def scenario():
        state = store(tmp_path)
        old, replacement = RejectedTransport(), RejectedTransport()
        calls = []
        async def renew():
            calls.append(True)
            return replacement
        client = AsyncClient(old, state, reauthenticate=renew)
        try:
            for _ in range(2):
                with pytest.raises(SessionExpiredError):
                    await client._read('getChats', {})
            assert calls == [True]
            assert len(replacement.calls) == 1
        finally:
            await client.aclose()
            state.close()
    asyncio.run(scenario())


def test_session_pool_waits_for_cancelled_startup_before_closing_clients(monkeypatch):
    from fnc_rubika.sessions import SessionPool
    class Member:
        def __init__(self, name, **kwargs):
            self.name = name
            self.cancelled = False
        def has_session(self):
            return True
        async def start(self):
            if self.name == 'broken':
                await asyncio.sleep(0)
                raise TransportError('Startup failed')
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        async def aclose(self):
            if self.name != 'broken':
                assert self.cancelled, 'Startup task still running when its session closes'
    monkeypatch.setattr('fnc_rubika.sessions.Client', Member)
    async def scenario():
        pool = SessionPool('broken', 'waiting')
        with pytest.raises(TransportError, match='Startup failed'):
            await pool.__aenter__()
        assert pool['waiting'].cancelled
    asyncio.run(scenario())


@pytest.mark.parametrize('reply', ['bad_json', 'missing_hash', 'server_error', 'success'])
def test_upload_requires_confirmed_response_and_final_access_hash(tmp_path, reply):
    async def scenario():
        path = tmp_path/'upload.bin'
        path.write_bytes(b'media bytes')
        parts = []
        def server(request):
            if request.url.host == 'storage.iranlms.ir':
                parts.append(request.content)
                assert request.headers['part-number'] == '1'
                assert request.headers['total-part'] == '1'
                if reply == 'server_error':
                    return httpx.Response(503)
                if reply == 'bad_json':
                    return httpx.Response(200, text='broken')
                data = {'access_hash_rec': 'download-hash'} if reply == 'success' else {}
                return httpx.Response(200, json={'status_det': 'OK', 'data': data})
            inner = RubikaCipher(AUTH).decrypt(json.loads(request.content)['data_enc'])
            assert inner['method'] == 'requestSendFile'
            result = {'file_id': '1', 'dc_id': '1', 'access_hash_send': 'upload-hash', 'upload_url': 'https://storage.iranlms.ir/'}
            return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt({'status': 'OK', 'data': result})})
        registry = ContractRegistry.from_file(default_catalog_path())
        transport = RubikaTransport(registry, Session(AUTH), http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/']}
        try:
            if reply == 'success':
                result = await transport.request('media.upload', {'file_path': str(path)}, idempotency_key='one')
                assert result['access_hash_rec'] == 'download-hash'
            else:
                with pytest.raises(AmbiguousDeliveryError):
                    await transport.request('media.upload', {'file_path': str(path)}, idempotency_key='one')
            assert parts == [b'media bytes']
        finally:
            await transport.aclose()
    asyncio.run(scenario())
