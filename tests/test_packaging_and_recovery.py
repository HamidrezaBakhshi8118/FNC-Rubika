import asyncio
from fnc_rubika import Client, EncryptedSQLiteStore, PassphraseKeyProvider, Session
from fnc_rubika.contracts import ContractRegistry


def test_sending_operation_becomes_unknown_after_process_restart(tmp_path):
    path = tmp_path/'state.db'
    provider = PassphraseKeyProvider('long test passphrase')
    first = EncryptedSQLiteStore(path, key_provider=provider)
    operation = first.enqueue_operation('messages.send', {'text': 'test'})
    first.claim_operation()
    first.close()
    second = EncryptedSQLiteStore(path, key_provider=provider)
    try:
        assert second.operation_state(operation.operation_id)['state'] == 'unknown'
        assert second.claim_operation() is None
    finally:
        second.close()


def test_sync_named_client_logs_in_and_exposes_catalog(tmp_path):
    class Auth:
        async def begin(self, phone):
            return 'challenge'
        async def complete(self, challenge, code):
            return Session('token')
    class Transport:
        def __init__(self, registry):
            self.registry = registry
        async def request(self, operation, payload, *, idempotency_key):
            return {'chats': []}
        async def stream_events(self, cursor):
            await asyncio.sleep(3600)
            yield {}
        async def aclose(self):
            pass
    registry = ContractRegistry.from_mapping({'version': 'test', 'base_url': 'https://example.invalid',
        'endpoints': [{'operation': 'getChats', 'method': 'POST', 'path': '/'}]})
    named = Client('sync', registry=registry, data_dir=tmp_path, key_provider=PassphraseKeyProvider('long test passphrase'),
                   authenticator_factory=Auth, input_func=lambda _: '09123456789', otp_input_func=lambda _: '12345')
    named._transport = lambda _: Transport(registry)
    with named as client:
        assert client.api.getChats() == {'chats': []}
        assert client.getChats() == {'chats': []}
