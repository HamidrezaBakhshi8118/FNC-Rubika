from __future__ import annotations

from datetime import timedelta

from fnc_rubika.models import EventEnvelope
from fnc_rubika.storage import EncryptedSQLiteStore, PassphraseKeyProvider


def store(tmp_path):
    return EncryptedSQLiteStore(tmp_path / "session.sqlite3", key_provider=PassphraseKeyProvider("a long test passphrase"))


def test_secrets_and_payloads_are_not_plaintext(tmp_path):
    value = store(tmp_path)
    value.save_secret("session", {"access_token": "token-that-must-not-appear"})
    queued = value.enqueue_operation("messages.send", {"text": "private message"})

    assert value.load_secret("session") == {"access_token": "token-that-must-not-appear"}
    disk = (tmp_path / "session.sqlite3").read_bytes()
    assert b"token-that-must-not-appear" not in disk
    assert b"private message" not in disk
    assert value.operation_state(queued.operation_id)["state"] == "queued"


def test_inbox_deduplicates_then_advances_cursor_on_ack(tmp_path):
    value = store(tmp_path)
    event = EventEnvelope("event-1", "message", {"text": "hello"}, cursor="cursor-1")

    assert value.record_event(event) is True
    assert value.record_event(event) is False
    claimed = value.claim_event(lease_seconds=1)
    assert claimed == event
    value.acknowledge_event("event-1", "cursor-1")

    assert value.get_cursor() == "cursor-1"
    assert value.claim_event() is None
    assert value.purge_acknowledged_events(older_than=timedelta(seconds=0)) == 1


def test_outbox_retry_and_result(tmp_path):
    value = store(tmp_path)
    queued = value.enqueue_operation("messages.send", {"text": "hello"}, idempotency_key="idem-1")
    claimed = value.claim_operation()
    assert claimed["operation_id"] == queued.operation_id
    assert claimed["attempts"] == 1
    value.retry_operation(queued.operation_id, delay_seconds=0, error="temporary")
    assert value.claim_operation()["attempts"] == 2
    value.complete_operation(queued.operation_id, {"message_id": "1"})
    assert value.operation_state(queued.operation_id)["result"] == {"message_id": "1"}

