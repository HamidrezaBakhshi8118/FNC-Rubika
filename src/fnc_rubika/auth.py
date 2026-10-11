"""Contract-driven OTP flow and high-level named-session client."""

from __future__ import annotations

import asyncio
from datetime import datetime
import os
from pathlib import Path
import re
from collections.abc import AsyncIterator
from typing import Any, Callable, Mapping
from uuid import uuid4

from .client import AsyncClient, OtpAuthenticator
from .contracts import AuthenticationSpec, ContractRegistry
from .exceptions import ContractError, SecurityConfigurationError
from .models import Session
from .storage import EncryptedSQLiteStore, KeyProvider, KeyringKeyProvider
from .transport import HttpWebSocketTransport


_SESSION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_IRAN_PHONE = re.compile(r"\+989\d{9}\Z")


def validate_iranian_phone(value: str) -> str:
    normalized = value.strip().replace(" ", "").replace("-", "")
    if not _IRAN_PHONE.fullmatch(normalized):
        raise ValueError("Phone number must use the +989XXXXXXXXX format")
    return normalized


def default_data_dir() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "fnc-rubika"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "fnc-rubika"


def default_catalog_path() -> Path:
    return Path(__file__).with_name("contracts") / "rubika-session.catalog.json"


def _extract(value: Mapping[str, Any], field: str) -> Any:
    current: Any = value
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ContractError(f"Authentication response is missing {field!r}")
        current = current[part]
    return current


class ContractOtpAuthenticator:
    """OTP implementation driven only by the active reviewed contract catalog."""

    def __init__(self, registry: ContractRegistry) -> None:
        self._registry = registry
        self._spec: AuthenticationSpec = registry.require_authentication()
        # Authentication endpoints in a reviewed catalog must declare auth=false.
        self._transport = HttpWebSocketTransport(registry, Session(access_token=""))

    async def begin(self, phone_number: str) -> str:
        phone_number = validate_iranian_phone(phone_number)
        response = await self._transport.request(
            self._spec.request_code_operation,
            {self._spec.phone_field: phone_number},
            idempotency_key=str(uuid4()),
        )
        return str(_extract(response, self._spec.challenge_field))

    async def complete(self, challenge_id: str, code: str) -> Session:
        code = code.strip()
        if not code:
            raise ValueError("The verification code cannot be empty")
        response = await self._transport.request(
            self._spec.verify_code_operation,
            {self._spec.challenge_field: challenge_id, self._spec.code_field: code},
            idempotency_key=str(uuid4()),
        )
        expires_at: datetime | None = None
        if self._spec.expires_at_field:
            raw_expiry = _extract(response, self._spec.expires_at_field)
            if raw_expiry:
                expires_at = datetime.fromisoformat(str(raw_expiry))
        device_id = str(_extract(response, self._spec.device_id_field)) if self._spec.device_id_field else None
        return Session(
            access_token=str(_extract(response, self._spec.token_field)),
            device_id=device_id,
            expires_at=expires_at,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()


class Client:
    """A named, encrypted session with an ergonomic async lifecycle.

    The usual application shape is ``async with Client("personal") as client``.
    Each name maps to a different encrypted SQLite file, inbox cursor, and
    outbox.  It is therefore safe to keep, for example, ``personal`` and
    ``business`` open in the same process.
    """

    def __init__(
        self,
        session_name: str,
        *,
        registry: ContractRegistry | None = None,
        contract_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        key_provider: KeyProvider | None = None,
    ) -> None:
        if not _SESSION_NAME.fullmatch(session_name):
            raise ValueError("Session name must contain 1-64 letters, numbers, '_' or '-' and begin with a letter or number")
        self.session_name = session_name
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.registry = registry or ContractRegistry.from_file(contract_path or default_catalog_path())
        self.store = EncryptedSQLiteStore(
            self.data_dir / f"{session_name}.sqlite3",
            key_provider=key_provider or KeyringKeyProvider(),
        )
        self._client: AsyncClient | None = None
        self._closed = False

    async def __aenter__(self) -> "Client":
        """Open the stored named session and start its receiver/outbox workers."""

        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Stop network workers and close this session's encrypted store."""

        await self.aclose()

    def has_session(self) -> bool:
        return self.store.load_secret("session") is not None

    def _build(self, session: Session) -> AsyncClient:
        return AsyncClient(HttpWebSocketTransport(self.registry, session), self.store)

    async def login(self, phone_number: str, code: str, *, authenticator: OtpAuthenticator | None = None) -> Session:
        phone_number = validate_iranian_phone(phone_number)
        owned_authenticator: ContractOtpAuthenticator | None = None
        if authenticator is None:
            owned_authenticator = ContractOtpAuthenticator(self.registry)
            authenticator = owned_authenticator
        try:
            challenge_id = await authenticator.begin(phone_number)
            session = await authenticator.complete(challenge_id, code)
        finally:
            if owned_authenticator is not None:
                await owned_authenticator.aclose()
        self.store.save_secret("session", session.as_dict())
        self._client = self._build(session)
        return session

    async def login_interactive(self, *, input_func: Callable[[str], str] = input) -> Session:
        phone = await asyncio.to_thread(input_func, "شماره روبیکا را با فرمت +989XXXXXXXXX وارد کنید: ")
        phone = validate_iranian_phone(phone)
        authenticator = ContractOtpAuthenticator(self.registry)
        try:
            challenge_id = await authenticator.begin(phone)
            code = await asyncio.to_thread(input_func, "کد تایید ارسال‌شده را وارد کنید: ")
            session = await authenticator.complete(challenge_id, code)
        finally:
            await authenticator.aclose()
        self.store.save_secret("session", session.as_dict())
        self._client = self._build(session)
        return session

    def async_client(self) -> AsyncClient:
        """Return the low-level client for advanced integrations.

        Most applications do not need this method: :class:`Client` forwards
        ``messages``, ``media``, ``api``, ``events()``, ``on()``, and ``run()``.
        """

        if self._client is not None:
            return self._client
        stored = self.store.load_secret("session")
        if stored is None:
            raise SecurityConfigurationError("No session exists. Run `fnc-rubika login <session-name>` first.")
        self._client = self._build(Session.from_dict(stored))
        return self._client

    async def start(self) -> None:
        """Start durable receiving and sending for this named session."""

        if self._closed:
            raise RuntimeError("This named session is closed and cannot be restarted")
        await self.async_client().start()

    @property
    def messages(self) -> Any:
        """Typed message service for this named session."""

        return self.async_client().messages

    @property
    def media(self) -> Any:
        """Typed media service for this named session."""

        return self.async_client().media

    @property
    def api(self) -> Any:
        """All operations that exist in the active reviewed catalog."""

        return self.async_client().api

    @property
    def session_expired(self) -> bool:
        """Whether the provider rejected this session and it needs manual login."""

        return self.async_client().session_expired

    def on(self, event_type: str, handler: Callable[..., Any] | None = None) -> Any:
        """Register a durable event handler; accepts ``@client.on("message")``."""

        return self.async_client().on(event_type, handler)

    def events(self) -> AsyncIterator[Any]:
        """Iterate durable deliveries and explicitly ``ack`` or ``nack`` each one."""

        return self.async_client().events()

    async def run(self, *, workers: int = 1) -> None:
        """Dispatch registered event handlers until cancelled or closed."""

        await self.async_client().run(workers=workers)

    async def wait_operation(self, operation_id: str, *, timeout: float | None = 30) -> Mapping[str, Any]:
        """Wait for a durable queued mutation to reach a terminal state."""

        return await self.async_client().wait_operation(operation_id, timeout=timeout)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            await self._client.aclose()
        self.store.close()
