from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from fnc_rubika import Session
from fnc_rubika.auth import default_catalog_path
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.rubika import RubikaCipher, RubikaTransport


AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


@pytest.mark.parametrize('authenticated', [False, True])
def test_web_referer_is_sent_for_discovery_and_encrypted_rpc(authenticated):
    async def scenario():
        methods = []

        def server(request):
            body = json.loads(request.content)
            if request.headers.get('Referer') != 'https://web.rubika.ir/':
                return httpx.Response(200, json={'status': 'ERROR_GENERIC', 'status_det': 'INVALID_AUTH'})
            if body.get('method') == 'getDCs':
                methods.append('getDCs')
                assert request.headers['Content-Type'] == 'application/json'
                return httpx.Response(200, json={'status': 'OK', 'data': {'default_api_urls': ['https://messenger.iranlms.ir/']}})
            token = AUTH if authenticated else body['tmp_session']
            inner = RubikaCipher(token).decrypt(body['data_enc'])
            methods.append(inner['method'])
            assert request.headers['Content-Type'] == 'text/plain'
            result = {'status': 'OK', 'data': {'chats': []} if authenticated else {'status': 'OK', 'phone_code_hash': 'challenge'}}
            return httpx.Response(200, json={'data_enc': RubikaCipher(token).encrypt(result)})

        registry = ContractRegistry.from_file(default_catalog_path())
        http = httpx.AsyncClient(transport=httpx.MockTransport(server))
        transport = RubikaTransport(registry, Session(AUTH if authenticated else ''), http_client=http)
        try:
            if authenticated:
                assert await transport.rpc('getChats', {}) == {'chats': []}
            else:
                result = await transport.rpc('sendCode', {'phone_number': '989123456789', 'send_type': 'SMS'}, authenticated=False)
                assert result['phone_code_hash'] == 'challenge'
            assert methods == ['getDCs', 'getChats' if authenticated else 'sendCode']
        finally:
            await transport.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize('direction', ['upload', 'download'])
def test_web_referer_is_sent_to_media_storage(tmp_path, direction):
    async def scenario():
        storage_calls = []

        def server(request):
            assert request.headers.get('Referer') == 'https://web.rubika.ir/'
            if request.url.host == 'storage.iranlms.ir':
                storage_calls.append(request)
                if direction == 'download':
                    return httpx.Response(200, content=b'media')
                assert request.content == b'media'
                return httpx.Response(200, json={'status_det': 'OK', 'data': {'access_hash_rec': 'download-hash'}})
            inner = RubikaCipher(AUTH).decrypt(json.loads(request.content)['data_enc'])
            assert inner['method'] == 'requestSendFile'
            result = {'file_id': '1', 'dc_id': '1', 'access_hash_send': 'upload-hash', 'upload_url': 'https://storage.iranlms.ir/'}
            return httpx.Response(200, json={'data_enc': RubikaCipher(AUTH).encrypt({'status': 'OK', 'data': result})})

        registry = ContractRegistry.from_file(default_catalog_path())
        transport = RubikaTransport(registry, Session(AUTH), http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        transport._dcs = {'default_api_urls': ['https://messenger.iranlms.ir/'], 'storages': {'1': 'https://storage.iranlms.ir/'}}
        try:
            if direction == 'upload':
                source = tmp_path / 'upload.bin'
                source.write_bytes(b'media')
                result = await transport.request('media.upload', {'file_path': str(source)}, idempotency_key='one')
                assert result['access_hash_rec'] == 'download-hash'
            else:
                destination = tmp_path / 'download.bin'
                await transport.download({'file_id': '1', 'dc_id': '1', 'access_hash_rec': 'download-hash', 'size': 5}, destination)
                assert destination.read_bytes() == b'media'
            assert len(storage_calls) == 1
        finally:
            await transport.aclose()

    asyncio.run(scenario())
