from __future__ import annotations

import asyncio
import base64
import json

from Crypto.Cipher import PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
import httpx
import pytest
import websockets

from fnc_rubika.auth import default_catalog_path
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.exceptions import ContractError, RemoteOperationError, SessionExpiredError, TwoStepRequiredError
from fnc_rubika.models import Session
from fnc_rubika.rubika import RubikaCipher, RubikaOtpAuthenticator, RubikaTransport, transform_auth

AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


def registry():
    return ContractRegistry.from_file(default_catalog_path())


def test_session_roundtrip_and_repr_hides_auth_and_private_key():
    session = Session(AUTH, private_key='private-material', api_version='6')
    assert Session.from_dict(session.as_dict()) == session
    assert AUTH not in repr(session)
    assert 'private-material' not in repr(session)


def test_cipher_and_transform_reject_invalid_material():
    cipher = RubikaCipher(AUTH)
    payload = {'method': 'getChats', 'input': {'text': 'سلام'}}
    # Independent AES-256-CBC result from Node's built-in crypto implementation.
    assert cipher.encrypt(payload) == 'IEckN7C7qoOc10LWsbiHt3aBP2bpcFd1HHwNGDzNfduLxj4SwoQaws0Wxv6Q/Fy9t7eM0c6KaBecjiDTuL8s9Q=='
    assert cipher.decrypt(cipher.encrypt(payload)) == payload
    assert transform_auth(transform_auth('AZaz09+/=')) == 'AZaz09+/='
    with pytest.raises(ContractError):
        RubikaCipher('short')
    with pytest.raises(Exception, match='encrypted frame'):
        cipher.decrypt('invalid')


def test_full_otp_v6_login_and_signed_rpc_against_independent_server():
    async def scenario():
        calls = []
        auth_key = None

        def server(request):
            nonlocal auth_key
            body = json.loads(request.content)
            if body.get('method') == 'getDCs':
                return httpx.Response(200, json={'status': 'OK', 'data': {'default_api_urls': ['https://messenger.iranlms.ir/']}})
            token = body.get('tmp_session') or AUTH
            data = RubikaCipher(token).decrypt(body['data_enc'])
            calls.append(data['method'])
            if data['method'] == 'sendCode':
                assert data['input'] == {'phone_number': '989123456789', 'send_type': 'SMS'}
                result = {'status': 'OK', 'phone_code_hash': 'challenge'}
            elif data['method'] == 'signIn':
                assert data['input']['phone_code_hash'] == 'challenge'
                public = base64.b64decode(transform_auth(data['input']['public_key']))
                auth_key = RSA.import_key(public)
                result = {'status': 'OK', 'auth': base64.b64encode(PKCS1_OAEP.new(auth_key).encrypt(AUTH.encode())).decode(), 'user': {'user_guid': 'user-1'}}
            else:
                assert body['auth'] == transform_auth(AUTH)
                assert body['api_version'] == '6'
                pkcs1_15.new(auth_key).verify(SHA256.new(body['data_enc'].encode()), base64.b64decode(body['sign']))
                result = {'chats': []}
            return httpx.Response(200, json={'data_enc': RubikaCipher(token).encrypt({'status': 'OK', 'data': result})})

        login = RubikaOtpAuthenticator(registry())
        await login._transport._http.aclose()
        login._transport._http = httpx.AsyncClient(transport=httpx.MockTransport(server))
        try:
            challenge = await login.begin('09123456789')
            session = await login.complete(challenge, '12345')
            assert session.account_id == 'user-1'
        finally:
            await login.aclose()
        transport = RubikaTransport(registry(), session, http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        try:
            assert await transport.request('getChats', {}, idempotency_key='one') == {'chats': []}
        finally:
            await transport.aclose()
        assert calls == ['sendCode', 'signIn', 'getChats']
    asyncio.run(scenario())


def test_access_denied_does_not_trigger_session_login():
    with pytest.raises(RemoteOperationError):
        RubikaTransport._unwrap({'status': 'ERROR_GENERIC', 'status_det': 'INVALID_AUTH'})
    with pytest.raises(SessionExpiredError):
        RubikaTransport._unwrap({'status': 'ERROR_ACTION', 'status_det': 'INVALID_AUTH'})


def test_websocket_handshake_and_encrypted_batched_updates(monkeypatch):
    async def scenario():
        async def server(socket):
            handshake = json.loads(await socket.recv())
            assert handshake == {'api_version': '5', 'auth': AUTH, 'data': '', 'method': 'handShake'}
            await socket.send('{}')
            data = {'message_updates': [{'object_guid': 'chat', 'message': {'message_id': '1', 'text': 'سلام'}}],
                    'chat_updates': [{'object_guid': 'chat', 'count_unseen': 1}]}
            await socket.send(json.dumps({'type': 'messenger', 'data_enc': RubikaCipher(AUTH).encrypt(data)}))
            await socket.wait_closed()

        async with websockets.serve(server, '127.0.0.1', 0) as local:
            port = local.sockets[0].getsockname()[1]
            # Only this local server test replaces URL validation.
            monkeypatch.setattr('fnc_rubika.rubika._trusted_url', lambda value, **kwargs: value)
            transport = RubikaTransport(registry(), Session(AUTH))
            transport._dcs = {'default_sockets': [f'ws://127.0.0.1:{port}']}
            stream = transport.stream_events(None)
            try:
                first = await asyncio.wait_for(anext(stream), 2)
                second = await asyncio.wait_for(anext(stream), 2)
                assert first['type'] == 'message'
                assert second['type'] == 'chat'
                assert first['cursor'] is None
                duplicate = transport.decode_push({'type': 'messenger', 'messenger': {'message_updates': [first['payload']]}})
                assert duplicate[0]['event_id'] == first['event_id']
            finally:
                await stream.aclose()
                await transport.aclose()
    asyncio.run(scenario())


def test_catalog_has_all_observed_names_and_native_routing():
    catalog = registry()
    assert catalog.provider['rpc_method_count'] == 205
    assert len(catalog.operations()) == 211
    assert catalog.endpoint('getProfilesStoryList').dc_type == 'rubino'
    assert catalog.endpoint('getProfilesStoryList').wire_mode == 'service'
    assert catalog.endpoint('sendCode').auth is False
    assert catalog.endpoint('getWebAppFunction').target_url == 'https://webapp1.iranlms.ir'
