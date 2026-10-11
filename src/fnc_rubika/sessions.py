"""Lifecycle management for several independent named Rubika sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .auth import Client
from .contracts import ContractRegistry
from .storage import KeyProvider


class SessionPool:
    """Open multiple named sessions together without mixing their state.

    ``SessionPool("personal", "business")`` constructs one :class:`Client`
    per name.  Every member has a distinct encrypted database and transport;
    the pool merely gives them a single lifecycle boundary.
    """

    def __init__(
        self,
        *session_names: str,
        registry: ContractRegistry | None = None,
        contract_path: str | Path | None = None,
        data_dir: str | Path | None = None,
        key_provider: KeyProvider | None = None,
    ) -> None:
        if not session_names:
            raise ValueError("SessionPool requires at least one session name")
        if len(set(session_names)) != len(session_names):
            raise ValueError("Session names in a SessionPool must be unique")
        self._clients = {
            name: Client(
                name,
                registry=registry,
                contract_path=contract_path,
                data_dir=data_dir,
                key_provider=key_provider,
            )
            for name in session_names
        }
        self._closed = False

    async def __aenter__(self) -> "SessionPool":
        """Start all stored sessions concurrently; close partial starts on error."""

        try:
            await asyncio.gather(*(client.start() for client in self._clients.values()))
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def names(self) -> tuple[str, ...]:
        """Session names in creation order."""

        return tuple(self._clients)

    def get(self, session_name: str) -> Client:
        """Return one named client or raise ``KeyError`` when it is absent."""

        return self._clients[session_name]

    def __getitem__(self, session_name: str) -> Client:
        return self.get(session_name)

    def __iter__(self) -> Iterator[Client]:
        return iter(self._clients.values())

    async def aclose(self) -> None:
        """Close every member; safe to call more than once."""

        if self._closed:
            return
        self._closed = True
        await asyncio.gather(*(client.aclose() for client in self._clients.values()), return_exceptions=True)
