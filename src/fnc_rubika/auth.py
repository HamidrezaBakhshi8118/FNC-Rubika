"""Contract-driven OTP flow and high-level named-session client."""

from __future__ import annotations

import asyncio
from datetime import datetime
from getpass import getpass
import os
from pathlib import Path
import re
import threading
from collections.abc import AsyncIterator
from typing import Any, Callable, Mapping
from uuid import uuid4

from .client import AsyncClient, OtpAuthenticator
from .contracts import AuthenticationSpec, ContractRegistry
from .exceptions import ContractError, SecurityConfigurationError, InvalidCodeError, TwoStepRequiredError, SessionExpiredError
from .models import Session
from .storage import EncryptedSQLiteStore, KeyProvider, KeyringKeyProvider
from .terminal import info as terminal_info
from .terminal import prompt_label, success as terminal_success
from .transport import HttpWebSocketTransport


_SESSION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_IRAN_PHONE = re.compile(r"\+989\d{9}\Z")
_TERMINAL_LOGIN_LOCK = threading.Lock()


def validate_iranian_phone(value: str) -> str:
    normalized = value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).strip().replace(" ", "").replace("-", "")
    if normalized.startswith('0098'):
        normalized = '+'+normalized[2:]
    elif normalized.startswith('98'):
        normalized = '+'+normalized
    elif normalized.startswith('09'):
        normalized = '+98'+normalized[1:]
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
        auto_login: bool = True,
        authenticator_factory: Callable[[], OtpAuthenticator] | None = None,
        input_func: Callable[[str], str] = input,
        otp_input_func: Callable[[str], str] = getpass,
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
        self.auto_login = auto_login
        self._authenticator_factory = authenticator_factory
        self._input_func = input_func
        self._otp_input_func = otp_input_func
        self._start_lock = asyncio.Lock()
        self._handlers: list[tuple[str, Callable[..., Any]]] = []

    async def __aenter__(self) -> "Client":
        """Open a session, interactively creating it when no session exists."""

        try:
            await self.start()
        except BaseException:
            await self.aclose()
            raise
        return self

    def __enter__(self):
        from .sync import SyncClient
        self._sync = SyncClient(self)
        try:
            return self._sync.__enter__()
        except BaseException:
            self._sync.close()
            raise

    def __exit__(self, *_: object) -> None:
        self._sync.close()

    def __getattr__(self, name: str):
        registry = self.__dict__.get('registry')
        if registry is None or name.startswith('_') or name not in registry.operations():
            raise AttributeError(name)
        async def call(*, wait: bool = True, timeout: float | None = 30, **payload):
            await self.start()
            return await self.api.call(name, payload, wait=wait, timeout=timeout)
        return call

    async def __aexit__(self, *_: object) -> None:
        """Stop network workers and close this session's encrypted store."""

        await self.aclose()

    def has_session(self) -> bool:
        return self.store.load_secret("session") is not None

    def _build(self, session: Session) -> AsyncClient:
        client = AsyncClient(self._transport(session), self.store,
                             reauthenticate=self._renew_transport if self.auto_login else None)
        for event_type, handler in self._handlers:
            client.on(event_type, handler)
        return client

    def _transport(self, session: Session):
        if self.registry.protocol == 'rubika':
            from .rubika import RubikaTransport
            return RubikaTransport(self.registry, session)
        return HttpWebSocketTransport(self.registry, session)

    def _authenticator(self) -> OtpAuthenticator:
        if self._authenticator_factory is not None:
            return self._authenticator_factory()
        if self.registry.protocol == 'rubika':
            from .rubika import RubikaOtpAuthenticator
            return RubikaOtpAuthenticator(self.registry)
        return ContractOtpAuthenticator(self.registry)

    async def _renew_transport(self):
        terminal_info('The session has expired. Sign in again to continue.')
        session = await self._prompt_session(input_func=self._input_func, otp_input_func=self._otp_input_func)
        self._check_account(session)
        self.store.save_secret('session', session.as_dict())
        transport = self._transport(session)
        try:
            prepare = getattr(transport, 'prepare', None)
            if prepare:
                await prepare()
        except BaseException:
            await transport.aclose()
            raise
        return transport

    async def _save_session(self, session: Session) -> None:
        if self._closed:
            raise RuntimeError('This named session is closed')
        self._check_account(session)
        self.store.save_secret('session', session.as_dict())
        if self._client is None:
            self._client = self._build(session)
        else:
            await self._client.replace_transport(self._transport(session))

    def _check_account(self, session: Session) -> None:
        previous = self.store.load_secret('session')
        previous_id = previous.get('account_id') if previous else None
        if previous_id and previous_id != session.account_id:
            raise SecurityConfigurationError('This store belongs to another account; use a different session name')

    async def login(self, phone_number: str, code: str, *, authenticator: OtpAuthenticator | None = None) -> Session:
        phone_number = validate_iranian_phone(phone_number)
        if self._closed:
            raise RuntimeError('This named session is closed')
        owned_authenticator = None
        if authenticator is None:
            owned_authenticator = self._authenticator()
            authenticator = owned_authenticator
        try:
            challenge_id = await authenticator.begin(phone_number)
            session = await authenticator.complete(challenge_id, code)
        finally:
            if owned_authenticator is not None:
                close = getattr(owned_authenticator, 'aclose', None)
                if close:
                    await close()
        await self._save_session(session)
        return session

    async def login_interactive(
        self,
        *,
        input_func: Callable[[str], str] | None = None,
        otp_input_func: Callable[[str], str] | None = None,
        authenticator: OtpAuthenticator | None = None,
    ) -> Session:
        """Create this session from terminal input without echoing the OTP.

        Chroma styles non-secret prompt labels on supported Windows terminals.
        Phone number, verification code, and session material are never logged.
        """

        session = await self._prompt_session(input_func=input_func or self._input_func, otp_input_func=otp_input_func or self._otp_input_func, authenticator=authenticator)
        await self._save_session(session)
        terminal_success(f'Encrypted session "{self.session_name}" saved successfully.')
        return session

    async def _prompt_session(self, *, input_func: Callable[[str], str], otp_input_func: Callable[[str], str], authenticator: OtpAuthenticator | None = None) -> Session:
        if self._closed:
            raise RuntimeError('This named session is closed')
        owned_authenticator = None
        if authenticator is None:
            owned_authenticator = self._authenticator()
            authenticator = owned_authenticator
        acquired = False
        try:
            while not _TERMINAL_LOGIN_LOCK.acquire(blocking=False):
                await asyncio.sleep(0.05)
            acquired = True
            terminal_info(f'Creating encrypted session "{self.session_name}"')
            for attempt in range(3):
                phone = await asyncio.to_thread(input_func, prompt_label('Rubika phone number (09... or +989...)'))
                try:
                    phone = validate_iranian_phone(phone)
                    break
                except ValueError:
                    terminal_info('Invalid phone number format.')
            else:
                raise ValueError('A valid Iranian phone number is required')
            try:
                challenge_id = await authenticator.begin(phone)
            except TwoStepRequiredError:
                begin_with_password = getattr(authenticator, 'begin_with_password', None)
                if begin_with_password is None:
                    raise
                for attempt in range(3):
                    password = await asyncio.to_thread(otp_input_func, prompt_label('Rubika two-step password'))
                    try:
                        challenge_id = await begin_with_password(phone, password)
                        break
                    except TwoStepRequiredError:
                        terminal_info('The two-step password was rejected. Try again.')
                else:
                    raise TwoStepRequiredError('The existing two-step password was rejected')
            terminal_info('Verification code sent. Enter it below; input is hidden.')
            for attempt in range(3):
                code = await asyncio.to_thread(otp_input_func, prompt_label('Verification code'))
                code = code.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).strip()
                if not code:
                    terminal_info('The verification code is empty.')
                    continue
                try:
                    return await authenticator.complete(challenge_id, code)
                except InvalidCodeError:
                    terminal_info('The verification code was rejected. Try again.')
            raise InvalidCodeError('The verification code was rejected after three attempts')
        finally:
            try:
                if owned_authenticator is not None:
                    close = getattr(owned_authenticator, 'aclose', None)
                    if close:
                        await close()
            finally:
                if acquired:
                    _TERMINAL_LOGIN_LOCK.release()

    def async_client(self) -> AsyncClient:
        """Return the low-level client for advanced integrations.

        Most applications do not need this method: :class:`Client` forwards
        ``messages``, ``media``, ``api``, ``events()``, ``on()``, and ``run()``.
        """

        if self._client is not None:
            return self._client
        stored = self.store.load_secret("session")
        if stored is None:
            raise SecurityConfigurationError("No session exists. Enter the client through `async with Client(...)` to sign in interactively.")
        self._client = self._build(Session.from_dict(stored))
        return self._client

    async def start(self) -> None:
        """Create a missing session interactively, then start durable I/O."""

        if self._closed:
            raise RuntimeError("This named session is closed and cannot be restarted")
        async with self._start_lock:
            stored = self.store.load_secret('session')
            expired = stored is not None and Session.from_dict(stored).is_expired
            if stored is None or expired:
                if not self.auto_login:
                    raise SessionExpiredError('No valid session exists and automatic login is disabled')
                await self.login_interactive()
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

        def register(callback):
            self._handlers.append((event_type, callback))
            if self._client is not None:
                self._client.on(event_type, callback)
            return callback
        return register if handler is None else register(handler)

    async def events(self) -> AsyncIterator[Any]:
        """Iterate durable deliveries and explicitly ``ack`` or ``nack`` each one."""

        await self.start()
        async for delivery in self.async_client().events():
            yield delivery

    async def run(self, *, workers: int = 1) -> None:
        """Dispatch registered event handlers until cancelled or closed."""

        await self.start()
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
