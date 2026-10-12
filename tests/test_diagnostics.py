from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from fnc_rubika import Session
from fnc_rubika import __main__ as cli
from fnc_rubika.auth import default_catalog_path
from fnc_rubika.contracts import ContractRegistry
from fnc_rubika.diagnostics import diagnose_access
from fnc_rubika.exceptions import AccessDeniedError, SessionExpiredError
from fnc_rubika.rubika import RubikaTransport


AUTH = 'abcdefghijklmnopqrstuvwxyz012345'


class ReadTransport:
    def __init__(self, *, denied_scope=None, can_send=True):
        self.denied_scope = denied_scope
        self.can_send = can_send
        self.calls = []

    async def request(self, operation, payload, *, idempotency_key):
        self.calls.append((operation, payload))
        assert operation in {'getChats', 'getUserInfo', 'getAbsObjects'}
        if self.denied_scope == 'all' or (self.denied_scope == 'destination' and payload.get('user_guid') == 'u-destination'):
            raise AccessDeniedError('secret credential in untrusted exception')
        if self.denied_scope == 'session':
            raise SessionExpiredError('secret session response')
        if operation == 'getChats':
            return {'chats': [{'object_guid': 'u-destination', 'title': 'secret chat title', 'last_message': {'text': 'secret message'}}]}
        return {'user': {'user_guid': payload['user_guid'], 'phone': 'secret phone'},
                'chat': {'status': 'Active', 'access': ['SendMessages'] if self.can_send else []}}


@pytest.mark.parametrize(('denied_scope', 'can_send', 'assessment'), [
    (None, True, 'read_access_verified_send_failure_unresolved'),
    (None, False, 'destination_send_permission_missing'),
    ('destination', True, 'destination_read_access_denied'),
    ('all', True, 'account_or_protocol_access_denied'),
    ('session', True, 'session_rejected'),
])
def test_diagnostics_distinguish_account_and_destination_without_exposing_private_data(denied_scope, can_send, assessment):
    transport = ReadTransport(denied_scope=denied_scope, can_send=can_send)
    report = asyncio.run(diagnose_access(transport, account_id='u-own-account', chat_id='u-destination'))
    assert report['assessment'] == assessment
    encoded = json.dumps(report)
    assert encoded.isascii()
    for secret in ['secret', 'u-own-account', 'u-destination']:
        assert secret not in encoded
    assert len(transport.calls) == 3


def test_diagnostic_cli_does_not_start_workers_or_change_session(monkeypatch, capsys):
    transport = ReadTransport()
    closed = []
    class LowLevel:
        def load_session(self):
            return Session('secret token', private_key='secret private key', account_id='u-own-account', api_version='6')
    low = LowLevel()
    low.transport = transport
    class Named:
        def __init__(self, name, *, auto_login):
            assert name == 'personal'
            assert auto_login is False
        def has_session(self):
            return True
        def async_client(self):
            return low
        async def aclose(self):
            closed.append(True)
        async def start(self):
            pytest.fail('Diagnostic command must not start outbox or realtime workers')
    monkeypatch.setattr(cli, 'Client', Named)
    monkeypatch.setattr(sys, 'argv', ['fnc-rubika', 'diagnose', 'personal', '--chat-id', 'u-destination'])
    assert cli.main() == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report['session_api_version'] == '6'
    assert report['read_access_verified']
    assert 'secret' not in output
    assert closed == [True]


@pytest.mark.parametrize('auth', ['', AUTH])
def test_dc_discovery_matches_web_plain_v4_auth_behavior(auth):
    async def scenario():
        def server(request):
            body = json.loads(request.content)
            assert body['api_version'] == '4'
            assert body['method'] == 'getDCs'
            assert body.get('auth') == (auth or None)
            assert 'sign' not in body
            assert request.headers['Content-Type'] == 'application/json'
            return httpx.Response(200, json={'status': 'OK', 'data': {'default_api_urls': ['https://messenger.iranlms.ir/']}})
        registry = ContractRegistry.from_file(default_catalog_path())
        transport = RubikaTransport(registry, Session(auth, api_version='6'), http_client=httpx.AsyncClient(transport=httpx.MockTransport(server)))
        try:
            assert await transport.discover() == {'default_api_urls': ['https://messenger.iranlms.ir/']}
        finally:
            await transport.aclose()
    asyncio.run(scenario())
