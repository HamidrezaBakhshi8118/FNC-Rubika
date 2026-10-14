from __future__ import annotations

import asyncio
import base64
import builtins
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from fnc_rubika import Client, EncryptedSQLiteStore, KeyringKeyProvider, PortableKeyProvider, SessionPool
from fnc_rubika.exceptions import SecurityConfigurationError
from fnc_rubika.models import EventEnvelope
from fnc_rubika.session_keys import SESSION_PASSWORD_ENV

PASSWORD = 'a strong portable test password'


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.delenv(SESSION_PASSWORD_ENV, raising=False)
    def deny(*args, **kwargs):
        raise AssertionError('Portable sessions must not access OS keyring')
    monkeypatch.setattr(KeyringKeyProvider, 'get_key', deny)


def close(client):
    asyncio.run(client.aclose())


def test_explicit_password_provider_bypasses_even_missing_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv(SESSION_PASSWORD_ENV, PASSWORD)
    original_import = builtins.__import__
    def no_keyring(name, *args, **kwargs):
        if name == 'keyring' or name.startswith('keyring.'):
            raise AssertionError('keyring import attempted')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_keyring)
    client = Client('headless', data_dir=tmp_path, auto_login=False,
                    key_provider=PortableKeyProvider(interactive=False))
    try:
        client.store.save_secret('session', {'access_token': 'private-test-token'})
        assert client.has_session()
    finally:
        close(client)
    assert not (tmp_path / 'headless.rubika.salt').exists()
    raw = (tmp_path / 'headless.rubika').read_bytes()
    assert PASSWORD.encode() not in raw and b'private-test-token' not in raw


def test_copy_single_file_to_different_directory_and_name(tmp_path):
    source_dir = tmp_path / 'Windows-side'
    client = Client('original', data_dir=source_dir, session_password=PASSWORD)
    client.store.save_secret('session', {'access_token': 'portable-token'})
    client.store.record_event(EventEnvelope('event-1', 'message', {'text': 'private-event'}))
    client.store.enqueue_operation('messages.send', {'text': 'private-queued-text'})
    source = client.session_path
    close(client)
    target_dir = tmp_path / 'Linux-side'
    target_dir.mkdir()
    shutil.copy2(source, target_dir / 'renamed.rubika')
    reopened = Client('renamed', data_dir=target_dir, session_password=PASSWORD)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'portable-token'
        assert reopened.store.claim_event().payload['text'] == 'private-event'
        assert reopened.store.claim_operation()['payload']['text'] == 'private-queued-text'
    finally:
        close(reopened)


def test_wrong_password_and_missing_password_never_change_existing_database(tmp_path, monkeypatch):
    client = Client('test', data_dir=tmp_path, session_password=PASSWORD)
    client.store.save_secret('session', {'access_token': 'important-original'})
    path = client.session_path
    close(client)
    before = path.read_bytes()
    with pytest.raises(SecurityConfigurationError, match='Incorrect session encryption password'):
        Client('test', data_dir=tmp_path, session_password='another sufficiently long password')
    assert path.read_bytes() == before
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SecurityConfigurationError, match=SESSION_PASSWORD_ENV):
        Client('test', data_dir=tmp_path)
    assert path.read_bytes() == before


def test_headless_without_password_fails_before_creating_database(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SecurityConfigurationError, match=SESSION_PASSWORD_ENV):
        Client('new', data_dir=tmp_path, key_provider=PortableKeyProvider())
    assert not (tmp_path / 'new.rubika').exists()


def test_hidden_interactive_password_is_confirmed_only_for_new_session(tmp_path, monkeypatch):
    import fnc_rubika.session_keys as keys
    prompts = []
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    def read(prompt):
        prompts.append(prompt)
        return PASSWORD
    monkeypatch.setattr(keys.getpass, 'getpass', read)
    first = Client('test', data_dir=tmp_path, key_provider=PortableKeyProvider())
    close(first)
    assert len(prompts) == 2
    second = Client('test', data_dir=tmp_path, key_provider=PortableKeyProvider())
    close(second)
    assert len(prompts) == 3


@pytest.mark.parametrize('password', ['', 'short', 123])
def test_bad_password_rejected_without_file(tmp_path, password):
    with pytest.raises(SecurityConfigurationError):
        Client('test', data_dir=tmp_path, session_password=password)
    assert not (tmp_path / 'test.rubika').exists()


def test_legacy_missing_key_is_actionable_and_never_generates_replacement(tmp_path, monkeypatch):
    class RawKey:
        def get_key(self, path):
            return b'a' * 32
    source = Client('old', data_dir=tmp_path, key_provider=RawKey())
    source.store.save_secret('session', {'access_token': 'keep-me'})
    path = source.session_path
    close(source)
    before = path.read_bytes()
    def unavailable(provider, path):
        assert provider._create is False
        raise SecurityConfigurationError('No original key')
    monkeypatch.setattr(KeyringKeyProvider, 'get_key', unavailable)
    with pytest.raises(SecurityConfigurationError, match='export-session --from-keyring'):
        Client('old', data_dir=tmp_path)
    assert path.read_bytes() == before


def test_legacy_existing_key_still_opens(tmp_path, monkeypatch):
    class RawKey:
        def get_key(self, path):
            return b'a' * 32
    source = Client('old', data_dir=tmp_path, key_provider=RawKey())
    source.store.save_secret('session', {'access_token': 'keep-me'})
    close(source)
    monkeypatch.setattr(KeyringKeyProvider, 'get_key', lambda self, path: b'a' * 32)
    reopened = Client('old', data_dir=tmp_path)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'keep-me'
    finally:
        close(reopened)


def test_export_legacy_reencrypts_every_record_and_preserves_source(tmp_path):
    class RawKey:
        def get_key(self, path):
            return b'a' * 32
    source = Client('old', data_dir=tmp_path, key_provider=RawKey())
    source.store.save_secret('session', {'access_token': 'secret-old-token'})
    source.store.set_cursor('old-cursor')
    source.store.record_event(EventEnvelope('event-1', 'message', {'text': 'event-private'}))
    delivered = source.store.enqueue_operation('messages.send', {'text': 'payload-private'})
    source.store.claim_operation()
    source.store.complete_operation(delivered.operation_id, {'message_id': 'old-result'})
    failed = source.store.enqueue_operation('messages.send', {'text': 'failed-private'})
    source.store.fail_operation(failed.operation_id, error='private-error', unknown=True)
    # Check a consistent source snapshot and all encrypted record types.
    source.store._connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = source.session_path.read_bytes()
    target = tmp_path / 'export' / 'portable.rubika'
    assert source.export_session(target, session_password=PASSWORD) == target
    assert source.session_path.read_bytes() == before
    assert source.store.load_secret('session')['access_token'] == 'secret-old-token'
    close(source)
    reopened = Client('portable', data_dir=target.parent, session_password=PASSWORD)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'secret-old-token'
        assert reopened.store.get_cursor() == 'old-cursor'
        assert reopened.store.claim_event().payload['text'] == 'event-private'
        assert reopened.store.operation_state(delivered.operation_id)['result']['message_id'] == 'old-result'
        assert reopened.store.operation_state(failed.operation_id)['error']['message'] == 'private-error'
    finally:
        close(reopened)
    data = target.read_bytes()
    for plain in (PASSWORD, 'secret-old-token', 'event-private', 'payload-private', 'private-error'):
        assert plain.encode() not in data
    assert list(target.parent.iterdir()) == [target]


def test_export_never_overwrites_destination_or_source(tmp_path):
    source = Client('test', data_dir=tmp_path, session_password=PASSWORD)
    existing = tmp_path / 'existing.rubika'
    existing.write_bytes(b'do not overwrite')
    try:
        for target in (existing, source.session_path):
            with pytest.raises(FileExistsError):
                source.export_session(target, session_password=PASSWORD)
        assert existing.read_bytes() == b'do not overwrite'
    finally:
        close(source)


def test_export_corrupted_record_cleans_up_and_keeps_original(tmp_path):
    source = Client('test', data_dir=tmp_path, session_password=PASSWORD)
    source.store.save_secret('session', {'access_token': 'test-token'})
    with source.store._connection:
        source.store._connection.execute("UPDATE secrets SET value=?", (b'corrupt',))
    target = tmp_path / 'export' / 'portable.rubika'
    try:
        with pytest.raises(SecurityConfigurationError):
            source.export_session(target, session_password=PASSWORD)
        assert not target.exists()
        assert not list(target.parent.iterdir())
    finally:
        close(source)


@pytest.mark.parametrize('field,value', [('n', 2**29), ('version', 99), ('salt', 'bad base64')])
def test_metadata_corruption_rejected_without_rewrite(tmp_path, field, value):
    client = Client('test', data_dir=tmp_path, session_password=PASSWORD)
    path = client.session_path
    close(client)
    with sqlite3.connect(path) as db:
        metadata = json.loads(db.execute('SELECT value FROM session_key').fetchone()[0])
        metadata[field] = value
        db.execute('UPDATE session_key SET value=?', (json.dumps(metadata),))
    before = path.read_bytes()
    with pytest.raises(SecurityConfigurationError):
        Client('test', data_dir=tmp_path, session_password=PASSWORD)
    assert path.read_bytes() == before


def test_session_pool_accepts_password_and_creates_independent_salts(tmp_path):
    pool = SessionPool('one', 'two', data_dir=tmp_path, session_password=PASSWORD)
    try:
        assert pool['one'].store._key != pool['two'].store._key
    finally:
        asyncio.run(pool.aclose())


def test_conflicting_key_options_rejected(tmp_path):
    with pytest.raises(ValueError, match='either key_provider or session_password'):
        Client('test', data_dir=tmp_path, session_password=PASSWORD, key_provider=PortableKeyProvider(PASSWORD))


def test_legacy_salt_passphrase_still_supported(tmp_path, monkeypatch):
    from fnc_rubika import PassphraseKeyProvider
    source = Client('old', data_dir=tmp_path, key_provider=PassphraseKeyProvider(PASSWORD))
    source.store.save_secret('session', {'access_token': 'legacy-pbkdf2'})
    close(source)
    monkeypatch.setenv(SESSION_PASSWORD_ENV, PASSWORD)
    reopened = Client('old', data_dir=tmp_path, auto_login=False)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'legacy-pbkdf2'
    finally:
        close(reopened)


def test_cli_export_readonly_preserves_interrupted_source_operation(tmp_path, monkeypatch, capsys):
    from fnc_rubika import __main__ as cli
    class RawKey:
        def get_key(self, path):
            return b'a' * 32
    source = Client('old', data_dir=tmp_path, key_provider=RawKey())
    source.store.save_secret('session', {'access_token': 'private-source-token'})
    operation = source.store.enqueue_operation('messages.send', {'text': 'pending-private'})
    source.store.claim_operation()
    close(source)
    original = (tmp_path / 'old.rubika').read_bytes()
    monkeypatch.setattr(KeyringKeyProvider, 'get_key', lambda self, path: b'a' * 32)
    monkeypatch.setenv(SESSION_PASSWORD_ENV, PASSWORD)
    target = tmp_path / 'portable' / 'server.rubika'
    monkeypatch.setattr(sys, 'argv', ['fnc-rubika', 'export-session', 'old', str(target),
                                     '--from-keyring', '--data-dir', str(tmp_path)])
    assert cli.main() == 0
    assert (tmp_path / 'old.rubika').read_bytes() == original
    assert 'private-source-token' not in capsys.readouterr().out
    exported = Client('server', data_dir=target.parent, session_password=PASSWORD)
    try:
        assert exported.store.load_secret('session')['access_token'] == 'private-source-token'
        assert exported.store.operation_state(operation.operation_id)['state'] == 'unknown'
        assert exported.store.claim_operation() is None
    finally:
        close(exported)


def test_readonly_store_cannot_modify_source(tmp_path):
    original = Client('test', data_dir=tmp_path, session_password=PASSWORD)
    original.store.save_secret('session', {'access_token': 'safe-token'})
    close(original)
    readonly = EncryptedSQLiteStore.open_readonly(
        tmp_path / 'test.rubika', key_provider=PortableKeyProvider(PASSWORD),
    )
    try:
        assert readonly.load_secret('session')['access_token'] == 'safe-token'
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            readonly.save_secret('session', {'access_token': 'must-not-replace'})
    finally:
        readonly.close()


def test_missing_export_source_does_not_create_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        EncryptedSQLiteStore.open_readonly(tmp_path / 'missing.rubika', key_provider=PortableKeyProvider(PASSWORD))
    assert not list(tmp_path.iterdir())
