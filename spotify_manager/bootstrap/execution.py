"""Own async clients and worker capacity for one web lifespan or CLI invocation."""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextvars import Token
from contextvars import copy_context
from dataclasses import dataclass
from dataclasses import field
from types import TracebackType
from typing import Literal

from spotify_manager.bootstrap.spotify_async import AsyncSpotifyRuntime
from spotify_manager.bootstrap.spotify_async import SpotifyRuntimeOptions
from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.infrastructure.async_work import BlockingBinding
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.cli_cancellation import CliCancellation
from spotify_manager.infrastructure.cli_cancellation import CliInterruptedError
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.interfaces.cli.terminal import TerminalSession
from spotify_manager.settings import Settings


type ClientKind = Literal["standard", "analysis", "interactive"]
_CURRENT: ContextVar[ExecutionRuntime | None] = ContextVar(
    "spotify_manager_execution", default=None
)


@dataclass
class ExecutionRuntime:
    """Keep clients on their creating loop until all invocation work has finished.

    Args:
        interactive: Whether original credential rotation may prompt on the CLI.
    """

    interactive: bool = False
    jobs: JobTasks = field(default_factory=JobTasks, init=False)
    genre_state_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    release_state_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _owner: AsyncSpotifyRuntime | None = field(default=None, init=False)
    _clients: dict[ClientKind, AsyncSpotify] = field(default_factory=dict, init=False)
    _construction: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _token: Token[ExecutionRuntime | None] | None = field(default=None, init=False)
    _workers: asyncio.Semaphore | None = field(default=None, init=False)
    _blocking: BlockingBinding | None = field(default=None, init=False)
    _shutdown: asyncio.Task[None] | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)

    async def __aenter__(self) -> ExecutionRuntime:
        """Bind this invocation before creating child tasks or pooled clients.

        Returns:
            This invocation's resource owner.
        """
        if self._token is not None or self._closed:
            raise RuntimeError("Execution runtime cannot be entered twice.")
        self._loop = asyncio.get_running_loop()
        self._workers = asyncio.Semaphore(4)
        self._blocking = BlockingBinding(self._workers)
        self._blocking.__enter__()
        self._token = _CURRENT.set(self)
        return self

    async def client(self, kind: ClientKind = "standard") -> AsyncSpotify:
        """Acquire a lazy client with its original retry and rotation scope.

        Args:
            kind: Original standard, mirror-analysis or interactive client role.

        Returns:
            A native client owned by this loop and runtime.
        """
        self._require_active()
        async with self._construction:
            self._require_active()
            if kind in self._clients:
                return self._clients[kind]
            if self._owner is None:
                owner = await self._open_owner()
                self._clients["standard"] = await owner.__aenter__()
                self._owner = owner
            if kind != "standard":
                self._clients[kind] = self._owner.profile(RetryProfile(0, 0, (999,)))
            return self._clients[kind]

    def _require_active(self) -> None:
        if self._closed or self._shutdown is not None or self._token is None:
            raise RuntimeError("Execution runtime is not active.")
        if self._loop is not asyncio.get_running_loop():
            raise RuntimeError("Execution runtime belongs to another event loop.")

    async def _open_owner(self) -> AsyncSpotifyRuntime:
        async with blocking_capacity():
            settings = asyncio.create_task(asyncio.to_thread(Settings))
            configuration = await finish_blocking(settings)
        return AsyncSpotifyRuntime(
            configuration, SpotifyRuntimeOptions(interactive=self.interactive)
        )

    async def fresh_client(self) -> AsyncSpotify:
        """Retain independent per-identity credential selection over the owned pool.

        Returns:
            Fresh original standard retry/rotation scope on this invocation's loop.
        """
        await self.client()
        self._require_active()
        assert self._owner is not None
        return self._owner.profile(RetryProfile())

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close clients before leaving their loop, including exceptional exits.

        Args:
            kind: Original context failure type.
            error: Original context failure.
            traceback: Original context traceback.
        """
        try:
            if self._shutdown is None:
                self._shutdown = asyncio.create_task(self._close())
            await finish_blocking(self._shutdown)
        finally:
            if self._token is not None:
                _CURRENT.reset(self._token)
                self._token = None
            if self._blocking is not None:
                self._blocking.__exit__(kind, error, traceback)

    async def _close(self) -> None:
        try:
            await self.jobs.close()
        finally:
            await self._close_owner()

    async def _close_owner(self) -> None:
        async with self._construction:
            self._closed = True
            if self._owner is not None:
                await self._owner.__aexit__(None, None, None)


def current_execution() -> ExecutionRuntime:
    """Read the outer runtime without constructing clients during business work.

    Returns:
        The current web lifespan or CLI invocation resource owner.

    Raises:
        RuntimeError: Execution has no owning entry boundary.
    """
    runtime = _CURRENT.get()
    if runtime is None:
        raise RuntimeError("Async execution requires an owning runtime.")
    return runtime


@dataclass
class ExecutionBinding:
    """Bind an existing lifespan owner to one request's task context.

    Args:
        runtime: Lifespan-owned resources for this request and its child jobs.
    """

    runtime: ExecutionRuntime
    _token: Token[ExecutionRuntime | None] | None = field(default=None, init=False)
    _blocking: BlockingBinding | None = field(default=None, init=False)

    def __enter__(self) -> None:
        """Enter this request's resource scope without creating any clients."""
        self.runtime._require_active()
        if self.runtime._workers is None:
            raise RuntimeError("Execution runtime is not active.")
        self._blocking = BlockingBinding(self.runtime._workers)
        self._blocking.__enter__()
        self._token = _CURRENT.set(self.runtime)

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the outer task context after request delivery.

        Args:
            kind: Original failure type.
            error: Original failure.
            traceback: Original failure traceback.
        """
        if self._token is not None:
            _CURRENT.reset(self._token)
            self._token = None
        if self._blocking is not None:
            self._blocking.__exit__(kind, error, traceback)


async def _invoke[T](operation: Coroutine[object, object, T]) -> T:
    with CliCancellation() as cancellation, TerminalSession():
        async with ExecutionRuntime(interactive=True):
            return await _await_cli_task(operation, cancellation)


async def _await_cli_task[T](
    operation: Coroutine[object, object, T], cancellation: CliCancellation
) -> T:
    task = asyncio.create_task(_execute(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancellation.request()
        await finish_blocking(task)
        raise


async def _execute[T](operation: Coroutine[object, object, T]) -> T:
    try:
        result = await operation
    except KeyboardInterrupt as error:
        raise CliInterruptedError("CLI execution interrupted.") from error
    check_cli_interruption()
    return result


def run_cli[T](operation: Coroutine[object, object, T]) -> T:
    """Run one parsed CLI invocation and close its resources on the same loop.

    Args:
        operation: Already named feature call selected by the command adapter.

    Returns:
        Original operation result.
    """
    try:
        return asyncio.run(_invoke(operation))
    except CliInterruptedError as error:
        raise KeyboardInterrupt from error


async def _invoke_python[T](operation: Coroutine[object, object, T]) -> T:
    async with ExecutionRuntime():
        return await operation


def run_python[T](operation: Coroutine[object, object, T]) -> T:
    """Close async resources at a retained synchronous Python API boundary.

    Args:
        operation: Explicitly named async counterpart of the public function.

    Returns:
        Original synchronous result, without replacing caller-owned standard input.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_invoke_python(operation))
    with ThreadPoolExecutor(max_workers=1) as executor:
        context = copy_context()
        task = executor.submit(context.run, asyncio.run, _invoke_python(operation))
        return task.result()
