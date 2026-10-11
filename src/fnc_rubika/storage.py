"""Encrypted SQLite state: sessions, inbox cursor, deduplication, and outbox."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Iterator, Mapping, Protocol
from uuid import uuid4

from Crypto.Cipher import AES

from .exceptions import SecurityConfigurationError
from .models import EventEnvelope, QueuedOperation


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> float:
    return (value or _now()).timestamp()


class KeyProvider(Protocol):
    def get_key(self, store_path: Path) -> bytes: ...


class PassphraseKeyProvider:
    """Derives a 256-bit key from an application-supplied passphrase and local salt."""

    def __init__(self, passphrase: str, *, iterations: int = 600_000) -> None:
        if len(passphrase) < 12:
            raise SecurityConfigurationError("Use a passphrase of at least 12 characters")
        self._passphrase = passphrase.encode("utf-8")
        self._iterations = iterations

    def get_key(self, store_path: Path) -> bytes:
        salt_path = store_path.with_suffix(store_path.suffix + ".salt")
        try:
            salt = salt_path.read_bytes()
        except FileNotFoundError:
            salt = secrets.token_bytes(32)
            try:
                with salt_path.open("xb") as handle:
                    handle.write(salt)
            except FileExistsError:
                salt = salt_path.read_bytes()
        if len(salt) < 16:
            raise SecurityConfigurationError("The session-store salt is invalid")
        return hashlib.pbkdf2_hmac("sha256", self._passphrase, salt, self._iterations, dklen=32)


class KeyringKeyProvider:
    """Gets a per-store key from the operating-system keyring when available."""

    def __init__(self, service_name: str = "fnc-rubika") -> None:
        self._service_name = service_name

    def get_key(self, store_path: Path) -> bytes:
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SecurityConfigurationError(
                "OS keyring support is unavailable; configure PassphraseKeyProvider instead"
            ) from exc
        account = hashlib.sha256(str(store_path.resolve()).encode("utf-8")).hexdigest()
        try:
            encoded = keyring.get_password(self._service_name, account)
            if encoded is None:
                key = secrets.token_bytes(32)
                keyring.set_password(self._service_name, account, base64.urlsafe_b64encode(key).decode("ascii"))
                return key
            key = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except Exception as exc:  # Keyring backends have non-uniform exception classes.
            raise SecurityConfigurationError("Unable to access the operating-system keyring") from exc
        if len(key) != 32:
            raise SecurityConfigurationError("The stored keyring key has an invalid length")
        return key


class EncryptedSQLiteStore:
    """AES-256-GCM encrypted application state with durable inbox and outbox tables."""

    def __init__(self, path: str | Path, *, key_provider: KeyProvider) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = key_provider.get_key(self.path)
        if len(self._key) != 32:
            raise SecurityConfigurationError("A session-store key must be 32 bytes")
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
            self._recover_interrupted_operations()

    def _recover_interrupted_operations(self) -> None:
        # One process owns each named store. After a crash, sending may have
        # reached the provider, so never automatically replay those mutations.
        rows = self._connection.execute("SELECT operation_id FROM outbox WHERE state='sending'").fetchall()
        for row in rows:
            self.fail_operation(str(row['operation_id']), error='Process stopped before delivery was confirmed', unknown=True)

    @classmethod
    def from_passphrase(cls, path: str | Path, passphrase: str) -> "EncryptedSQLiteStore":
        return cls(path, key_provider=PassphraseKeyProvider(passphrase))

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                name TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cursors (
                name TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inbox (
                event_id TEXT PRIMARY KEY,
                event BLOB NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending', 'processing', 'acknowledged')),
                lease_until REAL,
                received_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inbox_state ON inbox(state, lease_until, received_at);
            CREATE TABLE IF NOT EXISTS outbox (
                operation_id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                payload BLOB NOT NULL,
                idempotency_key TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('queued', 'sending', 'delivered', 'failed', 'unknown')),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                result BLOB,
                last_error BLOB,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_ready ON outbox(state, next_attempt_at, created_at);
            """
        )
        self._connection.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _seal(self, value: Any, *, aad: str) -> bytes:
        plaintext = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=secrets.token_bytes(12))
        cipher.update(aad.encode("utf-8"))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        return b"\x01" + cipher.nonce + tag + ciphertext

    def _open(self, value: bytes, *, aad: str) -> Any:
        if len(value) < 1 + 12 + 16 or value[0] != 1:
            raise SecurityConfigurationError("The encrypted session-store record is invalid")
        nonce, tag, ciphertext = value[1:13], value[13:29], value[29:]
        try:
            cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
            cipher.update(aad.encode("utf-8"))
            plaintext = cipher.decrypt_and_verify(ciphertext, tag)
            return json.loads(plaintext.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecurityConfigurationError("Unable to decrypt session-store record") from exc

    def save_secret(self, name: str, value: Mapping[str, Any]) -> None:
        blob = self._seal(dict(value), aad=f"secret:{name}")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO secrets(name, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (name, blob, _timestamp()),
            )

    def load_secret(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT value FROM secrets WHERE name=?", (name,)).fetchone()
        return None if row is None else dict(self._open(row["value"], aad=f"secret:{name}"))

    def delete_secret(self, name: str) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM secrets WHERE name=?", (name,))

    def get_cursor(self, name: str = "events") -> str | None:
        with self._lock:
            row = self._connection.execute("SELECT value FROM cursors WHERE name=?", (name,)).fetchone()
        return None if row is None else str(self._open(row["value"], aad=f"cursor:{name}")["value"])

    def set_cursor(self, value: str, name: str = "events") -> None:
        blob = self._seal({"value": value}, aad=f"cursor:{name}")
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO cursors(name, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (name, blob, _timestamp()),
            )

    def record_event(self, event: EventEnvelope) -> bool:
        blob = self._seal(event.as_dict(), aad=f"event:{event.event_id}")
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO inbox(event_id, event, state, lease_until, received_at) VALUES (?, ?, 'pending', NULL, ?)",
                (event.event_id, blob, _timestamp(event.received_at)),
            )
            return cursor.rowcount == 1

    def claim_event(self, *, lease_seconds: float = 60) -> EventEnvelope | None:
        now = _timestamp()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE inbox SET state='pending', lease_until=NULL "
                "WHERE state='processing' AND lease_until IS NOT NULL AND lease_until <= ?",
                (now,),
            )
            row = connection.execute(
                "SELECT event_id, event FROM inbox WHERE state='pending' ORDER BY received_at, event_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE inbox SET state='processing', lease_until=? WHERE event_id=?",
                (now + lease_seconds, row["event_id"]),
            )
        return EventEnvelope.from_dict(self._open(row["event"], aad=f"event:{row['event_id']}"))

    def acknowledge_event(self, event_id: str, cursor: str | None) -> None:
        with self._transaction() as connection:
            updated = connection.execute(
                "UPDATE inbox SET state='acknowledged', lease_until=NULL WHERE event_id=?", (event_id,)
            )
            if updated.rowcount != 1:
                return
            if cursor is not None:
                blob = self._seal({"value": cursor}, aad="cursor:events")
                connection.execute(
                    "INSERT INTO cursors(name, value, updated_at) VALUES ('events', ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (blob, _timestamp()),
                )

    def release_event(self, event_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE inbox SET state='pending', lease_until=NULL WHERE event_id=? AND state='processing'", (event_id,)
            )

    def enqueue_operation(self, operation: str, payload: Mapping[str, Any], *, idempotency_key: str | None = None) -> QueuedOperation:
        operation_id = str(uuid4())
        idempotency_key = idempotency_key or str(uuid4())
        blob = self._seal(dict(payload), aad=f"outbox:{operation_id}:payload")
        now = _timestamp()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO outbox(operation_id, operation, payload, idempotency_key, state, attempts, next_attempt_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'queued', 0, ?, ?, ?)",
                (operation_id, operation, blob, idempotency_key, now, now, now),
            )
        return QueuedOperation(operation_id, operation, idempotency_key)

    def claim_operation(self) -> dict[str, Any] | None:
        now = _timestamp()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox WHERE state='queued' AND next_attempt_at <= ? ORDER BY created_at LIMIT 1", (now,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE outbox SET state='sending', attempts=attempts+1, updated_at=? WHERE operation_id=?",
                (now, row["operation_id"]),
            )
        return {
            "operation_id": row["operation_id"],
            "operation": row["operation"],
            "payload": dict(self._open(row["payload"], aad=f"outbox:{row['operation_id']}:payload")),
            "idempotency_key": row["idempotency_key"],
            "attempts": int(row["attempts"]) + 1,
        }

    def operation_state(self, operation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM outbox WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        result = self._open(row["result"], aad=f"outbox:{operation_id}:result") if row["result"] else None
        error = self._open(row["last_error"], aad=f"outbox:{operation_id}:error") if row["last_error"] else None
        return {
            "operation_id": operation_id,
            "operation": row["operation"],
            "state": row["state"],
            "attempts": int(row["attempts"]),
            "result": result,
            "error": error,
        }

    def complete_operation(self, operation_id: str, result: Mapping[str, Any]) -> None:
        blob = self._seal(dict(result), aad=f"outbox:{operation_id}:result")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE outbox SET state='delivered', result=?, last_error=NULL, updated_at=? WHERE operation_id=?",
                (blob, _timestamp(), operation_id),
            )

    def retry_operation(self, operation_id: str, *, delay_seconds: float, error: str) -> None:
        blob = self._seal({"message": error}, aad=f"outbox:{operation_id}:error")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE outbox SET state='queued', next_attempt_at=?, last_error=?, updated_at=? WHERE operation_id=?",
                (_timestamp() + max(0, delay_seconds), blob, _timestamp(), operation_id),
            )

    def fail_operation(self, operation_id: str, *, error: str, unknown: bool = False, error_type: str | None = None) -> None:
        details = {"message": error}
        if error_type is not None:
            details['type'] = error_type
        blob = self._seal(details, aad=f"outbox:{operation_id}:error")
        state = "unknown" if unknown else "failed"
        with self._transaction() as connection:
            connection.execute(
                "UPDATE outbox SET state=?, last_error=?, updated_at=? WHERE operation_id=?",
                (state, blob, _timestamp(), operation_id),
            )

    def purge_acknowledged_events(self, *, older_than: timedelta) -> int:
        cutoff = _timestamp(_now() - older_than)
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM inbox WHERE state='acknowledged' AND received_at < ?", (cutoff,)
            )
            return cursor.rowcount
