"""Keep background tasks alive through their original safe cancellation boundary."""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.infrastructure.async_signal import AsyncSignal
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class RunningJob:
    """Pair an owned task with its job's cancellation request.

    Args:
        task: Scheduled feature worker.
        cancellation: Original safe-boundary cancellation signal.
    """

    task: asyncio.Task[None]
    cancellation: AsyncSignal


@dataclass
class JobTasks:
    """Own background work until shutdown can close its shared clients safely."""

    _running: list[RunningJob] = field(default_factory=list, init=False)
    _closing: bool = field(default=False, init=False)
    _shutdown: asyncio.Task[None] | None = field(default=None, init=False)

    def start(
        self,
        operation: Coroutine[object, object, None],
        cancellation: AsyncSignal,
        name: str,
    ) -> None:
        """Schedule an explicitly named worker independently of its HTTP request.

        Args:
            operation: Named interface worker call for the registered job.
            cancellation: This job's original cancellation request.
            name: Diagnostic task name retaining the feature and job ID.

        Raises:
            RuntimeError: Shutdown has already begun.
        """
        if self._closing:
            operation.close()
            raise RuntimeError("Job runtime is shutting down.")
        self._prune()
        task = asyncio.create_task(self._execute(operation), name=name)
        self._running.append(RunningJob(task, cancellation))

    async def _execute(self, operation: Coroutine[object, object, None]) -> None:
        try:
            await operation
        except (KeyboardInterrupt, SystemExit) as error:
            raise BackgroundControlError(str(error)) from error

    def _prune(self) -> None:
        pending = []
        for job in self._running:
            if not job.task.done():
                pending.append(job)
            elif not job.task.cancelled():
                job.task.exception()
        self._running = pending

    async def close(self) -> None:
        """Request safe stops and drain jobs before closing any shared clients."""
        if self._shutdown is None:
            self._closing = True
            self._shutdown = asyncio.create_task(self._drain())
        await finish_blocking(self._shutdown)

    async def _drain(self) -> None:
        pending = []
        for job in self._running:
            job.cancellation.set()
            pending.append(job.task)
        await asyncio.gather(*pending, return_exceptions=True)
        self._running.clear()


class BackgroundControlError(RuntimeError):
    """Retain a background worker's process-control failure without stopping ASGI."""
