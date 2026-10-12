"""Thread-backed synchronous facade for applications that do not use asyncio."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
import threading
from typing import Any

from .client import AsyncClient


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fnc-rubika-sync", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def run(self, coroutine: Any, timeout: float | None = None) -> Any:
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result(timeout)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class _SyncMessages:
    def __init__(self, owner: "SyncClient") -> None:
        self._owner = owner

    def send(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.send(*args, **kwargs))

    def reply(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.reply(*args, **kwargs))

    def edit(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.edit(*args, **kwargs))

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.delete(*args, **kwargs))

    def forward(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.forward(*args, **kwargs))

    def history(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.messages.history(*args, **kwargs))


class _SyncMedia:
    def __init__(self, owner: "SyncClient") -> None:
        self._owner = owner

    def upload(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.media.upload(*args, **kwargs))

    def download(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._run(self._owner._async.media.download(*args, **kwargs))


class SyncClient:
    """Synchronous facade backed by one private asyncio loop thread."""

    def __init__(self, client: AsyncClient) -> None:
        self._async = client
        self._loop = _LoopThread()
        self._closed = False
        self.messages = _SyncMessages(self)
        self.media = _SyncMedia(self)
        self.api = _SyncApi(self)

    def __getattr__(self, name: str):
        registry = getattr(self._async, 'registry', None) or getattr(self._async.transport, 'registry', None)
        if name.startswith('_') or registry is None or name not in registry.operations():
            raise AttributeError(name)
        def call(*, wait: bool = True, timeout: float | None = 30, **payload):
            return self.api.call(name, payload, wait=wait, timeout=timeout)
        return call

    def __enter__(self) -> "SyncClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _run(self, coroutine: Any, timeout: float | None = None) -> Any:
        return self._loop.run(coroutine, timeout)

    def start(self) -> None:
        self._run(self._async.start())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._run(self._async.aclose(), timeout=5)
        finally:
            self._loop.close()

    def begin_login(self, *args: Any, **kwargs: Any) -> Any:
        return self._run(self._async.begin_login(*args, **kwargs))

    def complete_login(self, *args: Any, **kwargs: Any) -> Any:
        return self._run(self._async.complete_login(*args, **kwargs))

    def on(self, event_type: str, handler: Callable[["SyncClient", Any], Any] | None = None):
        def register(callback: Callable[["SyncClient", Any], Any]):
            async def bridge(_: AsyncClient, delivery: Any) -> Any:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, callback, self, delivery)

            self._async.on(event_type, bridge)
            return callback

        return register if handler is None else register(handler)

    def run(self, *, workers: int = 1) -> None:
        self._run(self._async.run(workers=workers), timeout=None)


class _SyncApi:
    def __init__(self, owner: SyncClient, operation: str = '') -> None:
        self._owner = owner
        self._operation = operation

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        return _SyncApi(self._owner, f'{self._operation}.{name}' if self._operation else name)

    def __call__(self, **payload):
        return self.call(self._operation, **payload)

    def call(self, operation: str, payload=None, *, wait=True, timeout=30, **keyword_payload):
        async def invoke():
            await self._owner._async.start()
            return await self._owner._async.api.call(operation, payload, wait=wait, timeout=timeout, **keyword_payload)
        return self._owner._run(invoke())
