from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import stat
import sys
from types import SimpleNamespace

import pytest

from fnc_rubika import Client, FileKeyProvider, KeyringKeyProvider
from fnc_rubika.exceptions import SecurityConfigurationError
from fnc_rubika.session_keys import SESSION_PASSWORD_ENV


@pytest.fixture(autouse=True)
def no_password_or_os_keyring(monkeypatch):
    import fnc_rubika.session_keys as keys
    monkeypatch.delenv(SESSION_PASSWORD_ENV, raising=False)
    def denied(*args, **kwargs):
        raise AssertionError('Automatic sessions must not request a password or use OS keyring')
    monkeypatch.setattr(keys.getpass, 'getpass', denied)
    monkeypatch.setattr(KeyringKeyProvider, 'get_key', denied)
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(isatty=lambda: False))


def close(client):
    asyncio.run(client.aclose())


def test_default_creates_random_key_without_password_even_with_stale_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(SESSION_PASSWORD_ENV, 'stale password from older setup')
    client = Client('test', data_dir=tmp_path, auto_login=False)
    client.store.save_secret('session', {'access_token': 'private-session-token'})
    close(client)
    key = (tmp_path / 'test.rubika.key').read_bytes()
    assert len(key) == 32
    raw = (tmp_path / 'test.rubika').read_bytes()
    assert key not in raw and b'private-session-token' not in raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ['test.rubika', 'test.rubika.key']
    reopened = Client('test', data_dir=tmp_path, auto_login=False)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'private-session-token'
    finally:
        close(reopened)


def test_normal_login_only_asks_for_phone_and_otp(tmp_path, monkeypatch):
    from test_client_session_files import Auth, Transport
    async def scenario():
        auth = Auth()
        prompts = []
        def phone(prompt):
            prompts.append('phone')
            return '09123456789'
        def otp(prompt):
            prompts.append('otp')
            return '12345'
        client = Client('personal', data_dir=tmp_path, authenticator_factory=lambda: auth,
                        input_func=phone, otp_input_func=otp)
        client._transport = lambda _: Transport(client.registry)
        async with client:
            assert client.has_session()
        assert prompts == ['phone', 'otp']
        assert auth.logins == 1
        reopened = Client('personal', data_dir=tmp_path, auto_login=False,
                          input_func=phone, otp_input_func=otp)
        reopened._transport = lambda _: Transport(reopened.registry)
        async with reopened:
            assert reopened.has_session()
        assert prompts == ['phone', 'otp']
    asyncio.run(scenario())


def test_copied_database_and_key_reopen_under_new_name_without_password(tmp_path):
    client = Client('original', data_dir=tmp_path / 'first')
    client.store.save_secret('session', {'access_token': 'portable-automatic-token'})
    close(client)
    target = tmp_path / 'other-system'
    target.mkdir()
    shutil.copy2(tmp_path / 'first/original.rubika', target / 'renamed.rubika')
    shutil.copy2(tmp_path / 'first/original.rubika.key', target / 'renamed.rubika.key')
    reopened = Client('renamed', data_dir=target, auto_login=False)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'portable-automatic-token'
    finally:
        close(reopened)


def test_missing_key_never_regenerated_for_existing_database(tmp_path):
    client = Client('original', data_dir=tmp_path / 'first')
    client.store.save_secret('session', {'access_token': 'keep-token'})
    close(client)
    target = tmp_path / 'copy'
    target.mkdir()
    shutil.copy2(tmp_path / 'first/original.rubika', target / 'copied.rubika')
    before = (target / 'copied.rubika').read_bytes()
    with pytest.raises(SecurityConfigurationError, match='key file is missing'):
        Client('copied', data_dir=target)
    assert not (target / 'copied.rubika.key').exists()
    assert (target / 'copied.rubika').read_bytes() == before


@pytest.mark.parametrize('replacement', [b'short', bytes(32)])
def test_invalid_or_wrong_key_does_not_modify_existing_database(tmp_path, replacement):
    client = Client('original', data_dir=tmp_path)
    client.store.save_secret('session', {'access_token': 'keep-token'})
    close(client)
    (tmp_path / 'original.rubika.key').write_bytes(replacement)
    before = (tmp_path / 'original.rubika').read_bytes()
    with pytest.raises(SecurityConfigurationError):
        Client('original', data_dir=tmp_path)
    assert (tmp_path / 'original.rubika').read_bytes() == before
    assert (tmp_path / 'original.rubika.key').read_bytes() == replacement


def test_key_file_is_reused_when_only_database_was_removed(tmp_path):
    key = os.urandom(32)
    (tmp_path / 'new.rubika.key').write_bytes(key)
    client = Client('new', data_dir=tmp_path)
    close(client)
    assert (tmp_path / 'new.rubika.key').read_bytes() == key


def test_independent_sessions_have_independent_random_keys(tmp_path):
    first = Client('first', data_dir=tmp_path)
    second = Client('second', data_dir=tmp_path)
    close(first)
    close(second)
    assert (tmp_path / 'first.rubika.key').read_bytes() != (tmp_path / 'second.rubika.key').read_bytes()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX file permissions')
def test_new_key_and_database_are_owner_only_on_linux(tmp_path):
    client = Client('private', data_dir=tmp_path)
    close(client)
    for name in ('private.rubika', 'private.rubika.key'):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_automatic_export_creates_database_and_key_without_prompt(tmp_path):
    source = Client('original', data_dir=tmp_path)
    source.store.save_secret('session', {'access_token': 'exported-without-password'})
    target = tmp_path / 'export/server.rubika'
    source.export_session(target)
    close(source)
    assert (target.parent / 'server.rubika.key').is_file()
    reopened = Client('server', data_dir=target.parent, auto_login=False)
    try:
        assert reopened.store.load_secret('session')['access_token'] == 'exported-without-password'
    finally:
        close(reopened)
    assert sorted(p.name for p in target.parent.iterdir()) == ['server.rubika', 'server.rubika.key']


def test_export_never_overwrites_existing_key(tmp_path):
    source = Client('original', data_dir=tmp_path)
    target = tmp_path / 'export.rubika'
    key_path = tmp_path / 'export.rubika.key'
    key_path.write_bytes(b'existing-important-key')
    try:
        with pytest.raises(FileExistsError):
            source.export_session(target)
        assert key_path.read_bytes() == b'existing-important-key'
        assert not target.exists()
    finally:
        close(source)


def test_export_failure_cleans_its_published_key_without_overwriting_files(tmp_path, monkeypatch):
    source = Client('original', data_dir=tmp_path)
    source.store.save_secret('session', {'access_token': 'original-token'})
    target = tmp_path / 'export/server.rubika'
    original_link = os.link
    def fail_database_link(src, dest):
        if Path(dest) == target:
            raise FileExistsError('Simulated destination race')
        return original_link(src, dest)
    monkeypatch.setattr(os, 'link', fail_database_link)
    try:
        with pytest.raises(FileExistsError):
            source.export_session(target)
        assert not list(target.parent.iterdir())
        assert source.store.load_secret('session')['access_token'] == 'original-token'
    finally:
        close(source)


def test_symlink_key_is_rejected_without_touching_link_target(tmp_path):
    actual = tmp_path / 'actual'
    actual.write_bytes(bytes(32))
    try:
        (tmp_path / 'new.rubika.key').symlink_to(actual)
    except OSError:
        pytest.skip('Creating symlinks is unavailable')
    with pytest.raises(SecurityConfigurationError, match='regular file'):
        FileKeyProvider().get_key(tmp_path / 'new.rubika')
    assert actual.read_bytes() == bytes(32)
