"""Password-protected session keys that do not depend on an OS credential store."""
from __future__ import annotations

import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import warnings

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

from .exceptions import SecurityConfigurationError
from .storage import KeyringKeyProvider, PassphraseKeyProvider

SESSION_PASSWORD_ENV = "FNC_RUBIKA_SESSION_PASSWORD"
_CHECK = b"fnc-rubika portable session key v1"
_PARAMETERS = {"version": 1, "kdf": "scrypt", "n": 32768, "r": 8, "p": 1}


def session_password(password: str | None = None, *, confirm: bool = False,
                     interactive: bool = True) -> str:
    if password is None:
        password = os.environ.get(SESSION_PASSWORD_ENV)
    if password is None:
        if not interactive or not sys.stdin.isatty():
            raise SecurityConfigurationError(
                f"Set {SESSION_PASSWORD_ENV} to a strong password (12+ characters), "
                "or pass session_password= to Client. OS keyring is not required."
            )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("Session encryption password (12+ characters): ")
                if confirm and password != getpass.getpass("Confirm session encryption password: "):
                    raise SecurityConfigurationError("Session encryption passwords do not match")
        except getpass.GetPassWarning as exc:
            raise SecurityConfigurationError("Hidden password input is unavailable; use the session password environment variable") from exc
    if not isinstance(password, str) or len(password) < 12:
        raise SecurityConfigurationError("Use a strong session encryption password of at least 12 characters")
    return password


def inspect_store(path: Path):
    """Read metadata without creating a file or changing any existing records."""
    if not path.exists() or path.stat().st_size == 0:
        return None, False
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "session_key" in tables:
                row = connection.execute("SELECT value FROM session_key WHERE name='encryption'").fetchone()
                if row is not None:
                    return json.loads(row[0]), False
            legacy = any(connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
                         for table in ("secrets", "cursors", "inbox", "outbox") if table in tables)
            return None, legacy
        finally:
            connection.close()
    except (sqlite3.Error, ValueError, TypeError) as exc:
        raise SecurityConfigurationError("Invalid session database or encryption metadata") from exc


def _derive(password: str, salt: bytes) -> bytes:
    return scrypt(password.encode("utf-8"), salt, 32, N=32768, r=8, p=1)


def make_material(password: str):
    salt = secrets.token_bytes(32)
    key = _derive(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=secrets.token_bytes(12))
    cipher.update(_CHECK)
    ciphertext, tag = cipher.encrypt_and_digest(_CHECK)
    return key, {**_PARAMETERS, "salt": base64.b64encode(salt).decode("ascii"),
                 "check": base64.b64encode(cipher.nonce + tag + ciphertext).decode("ascii")}


def unlock_material(password: str, metadata) -> bytes:
    try:
        if not isinstance(metadata, dict) or any(metadata.get(k) != v for k, v in _PARAMETERS.items()):
            raise ValueError("unsupported encryption metadata")
        salt = base64.b64decode(metadata["salt"], validate=True)
        check = base64.b64decode(metadata["check"], validate=True)
        if len(salt) != 32 or len(check) != 28 + len(_CHECK):
            raise ValueError("invalid encryption metadata length")
        key = _derive(password, salt)
        cipher = AES.new(key, AES.MODE_GCM, nonce=check[:12])
        cipher.update(_CHECK)
        if cipher.decrypt_and_verify(check[28:], check[12:28]) != _CHECK:
            raise ValueError("invalid key check")
        return key
    except (ValueError, KeyError, TypeError) as exc:
        raise SecurityConfigurationError(
            "Incorrect session encryption password or damaged metadata; existing data was not changed"
        ) from exc


def write_material(connection, metadata):
    connection.execute("CREATE TABLE IF NOT EXISTS session_key (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "INSERT INTO session_key VALUES ('encryption', ?) "
        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
        (json.dumps(metadata, sort_keys=True, separators=(",", ":")),),
    )


class PortableKeyProvider:
    """Derive AES keys from a password and non-secret metadata inside the database."""

    def __init__(self, password: str | None = None, *, interactive: bool = True):
        self.password = password
        self.interactive = interactive

    def get_key(self, store_path: Path) -> bytes:
        store_path = Path(store_path)
        metadata, legacy = inspect_store(store_path)
        if legacy:
            raise SecurityConfigurationError(
                "Legacy session requires its original key provider. Export a portable session "
                "on the original system, or choose a new session name and sign in again."
            )
        password = session_password(self.password, confirm=metadata is None, interactive=self.interactive)
        if metadata is not None:
            return unlock_material(password, metadata)
        key, metadata = make_material(password)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(store_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        connection = sqlite3.connect(store_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Detect another creator instead of overwriting its encryption key.
            current, legacy = inspect_store(store_path)
            if current is not None or legacy:
                raise SecurityConfigurationError("Session changed during creation; reopen it")
            write_material(connection, metadata)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return key


class DefaultSessionKeyProvider:
    """Portable for new files; preserve access to existing explicit/OS-keyring files."""

    def __init__(self, password: str | None = None, *, interactive: bool = True):
        self.password = password
        self.interactive = interactive

    def get_key(self, store_path: Path) -> bytes:
        metadata, legacy = inspect_store(store_path)
        if metadata is not None or not legacy:
            return PortableKeyProvider(self.password, interactive=self.interactive).get_key(store_path)
        if store_path.with_suffix(store_path.suffix + ".salt").exists():
            password = session_password(self.password, interactive=self.interactive)
            return PassphraseKeyProvider(password).get_key(store_path)
        try:
            return KeyringKeyProvider(create=False).get_key(store_path)
        except SecurityConfigurationError as exc:
            raise SecurityConfigurationError(
                "This legacy session needs the original OS-keyring key. On the original system "
                "use export-session --from-keyring, or choose a new session name on this server."
            ) from exc
