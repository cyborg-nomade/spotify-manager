"""Scope terminal interruption to one CLI invocation and its blocking readers."""

import asyncio
import time
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from threading import Event
from types import TracebackType


class CliInterruptedError(RuntimeError):
    """Stop CLI execution at an accepted progress or checkpoint boundary."""


_CURRENT: ContextVar[CliCancellation | None] = ContextVar(
    "spotify_manager_cli_cancellation", default=None
)


@dataclass
class CliCancellation:
    """Own a CLI stop request without cancelling an in-flight business mutation."""

    requested: Event = field(default_factory=Event, init=False)
    wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _token: Token[CliCancellation | None] | None = field(default=None, init=False)

    def request(self) -> None:
        """Wake awaited retry delays and synchronous terminal readers."""
        self.requested.set()
        self.wake.set()

    def __enter__(self) -> CliCancellation:
        """Bind cancellation before creating the invocation's child task.

        Returns:
            This invocation's cancellation resource.
        """
        self._token = _CURRENT.set(self)
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the outer invocation context.

        Args:
            kind: Original failure type.
            error: Original failure.
            traceback: Original failure traceback.
        """
        if self._token is not None:
            _CURRENT.reset(self._token)
            self._token = None


def check_cli_interruption() -> None:
    """Observe CLI interruption only at a completed checkpoint or progress boundary.

    Raises:
        CliInterruptedError: This CLI invocation received an interruption request.
    """
    cancellation = _CURRENT.get()
    if cancellation is not None and cancellation.requested.is_set():
        raise CliInterruptedError("CLI execution interrupted.")


class InvocationWait:
    """Await original retry delays with CLI-only interruption support."""

    async def sleep(self, seconds: float) -> None:
        """Wait without blocking unrelated work or changing web retry decisions.

        Args:
            seconds: Original retry delay.

        Raises:
            CliInterruptedError: The CLI stop request arrives during this wait.
        """
        cancellation = _CURRENT.get()
        if cancellation is None:
            await asyncio.sleep(seconds)
            return
        check_cli_interruption()
        try:
            async with asyncio.timeout(max(0, seconds)):
                await cancellation.wake.wait()
        except TimeoutError:
            return
        check_cli_interruption()


INVOCATION_WAIT = InvocationWait()


class BlockingInvocationWait:
    """Retain SDK retry waits while allowing the CLI's blocking worker to stop."""

    def sleep(self, seconds: float) -> None:
        """Wait inside a bounded SDK worker, observing only its CLI stop request.

        Args:
            seconds: Original synchronous SDK retry delay.

        Raises:
            CliInterruptedError: The CLI stop request arrives during this wait.
            ValueError: The original delay is negative.
        """
        cancellation = _CURRENT.get()
        if cancellation is None or seconds < 0:
            time.sleep(seconds)
            return
        check_cli_interruption()
        cancellation.requested.wait(seconds)
        check_cli_interruption()
