"""Private, resilient session-client primitives for authorised Rubika use."""

from .client import AsyncClient
from .exceptions import AccessDeniedError, SessionRenewalError
from .auth import Client, ContractOtpAuthenticator, validate_iranian_phone
from .models import Delivery, EventEnvelope, MediaRef, Message, Session
from .storage import EncryptedSQLiteStore, KeyringKeyProvider, PassphraseKeyProvider
from .sync import SyncClient
from .sessions import SessionPool
from .rubika import RubikaOtpAuthenticator, RubikaTransport

__all__ = [
    "AccessDeniedError",
    "SessionRenewalError",
    "AsyncClient",
    "Client",
    "ContractOtpAuthenticator",
    "Delivery",
    "EncryptedSQLiteStore",
    "EventEnvelope",
    "KeyringKeyProvider",
    "MediaRef",
    "Message",
    "PassphraseKeyProvider",
    "Session",
    "SessionPool",
    "SyncClient",
    "RubikaOtpAuthenticator",
    "RubikaTransport",
    "validate_iranian_phone",
]
