"""Domain errors.  Messages must never include credentials or OTP values."""

from __future__ import annotations


class FncRubikaError(Exception):
    """Base exception for the package."""


class SecurityConfigurationError(FncRubikaError):
    """Secure session-key storage is unavailable or incorrectly configured."""


class ContractError(FncRubikaError):
    """The configured endpoint catalog is missing or inconsistent."""


class UnsupportedOperationError(ContractError):
    """An operation has no reviewed contract in the active catalog."""


class TransportError(FncRubikaError):
    """A request or realtime connection failed in a retryable way."""


class SessionExpiredError(TransportError):
    """The provider rejected the session; the application must re-authenticate."""


class RateLimitError(TransportError):
    """The provider requested a retry after a delay."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("The provider rate-limited this operation")
        self.retry_after = retry_after


class AmbiguousDeliveryError(TransportError):
    """The connection failed after a request may have reached the provider."""


class RemoteOperationError(FncRubikaError):
    """The provider returned a definitive, non-retryable operation failure."""


class OperationUnknownError(FncRubikaError):
    """A non-idempotent operation has an unresolved delivery outcome."""


class ClientClosedError(FncRubikaError):
    """The client was used after close."""

