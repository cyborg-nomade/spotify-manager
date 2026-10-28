"""Await original synchronous retry scopes without concealing their operations."""

import asyncio
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol
from typing import Self

from spotify_manager.application.ports.runtime import Retry
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy


class BlockingRetry(Protocol):
    """Retain the original caller-owned synchronous request policy."""

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open original request attempts.

        Args:
            description: Original operation label.

        Returns:
            Original ordered synchronous scopes.
        """
        ...


@dataclass(frozen=True)
class PythonRetry:
    """Accept either generation of a caller-owned retry resource.

    Args:
        source: Original synchronous or native async retry policy.
    """

    source: BlockingRetry | Retry

    def __bool__(self) -> bool:
        """Retain the caller's original fallback selection observation.

        Returns:
            Original resource truthiness.
        """
        return bool(self.source)

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Keep the operation in its caller and adapt only scope entry and exit.

        Args:
            description: Original operation label.

        Returns:
            Awaitable scopes with unchanged retry and suppression decisions.
        """
        return PythonAttempts(self.source.attempts(description))


@dataclass
class PythonAttempts(Iterator[AbstractAsyncContextManager[None]]):
    """Retain lazy attempt iteration and its original stopping boundary.

    Args:
        source: Original policy-owned attempt iterator.
    """

    source: Iterator[AbstractContextManager[None] | AbstractAsyncContextManager[None]]

    def __iter__(self) -> Self:
        """Continue the original attempt sequence.

        Returns:
            This scope adapter.
        """
        return self

    def __next__(self) -> AbstractAsyncContextManager[None]:
        """Advance once without eagerly consuming or reconstructing the policy.

        Returns:
            The original native scope or an adapter for its synchronous scope.

        Raises:
            StopIteration: The original policy finished.
        """
        scope = next(self.source)
        if isinstance(scope, AbstractAsyncContextManager):
            return scope
        return PythonAttempt(scope)


@dataclass(frozen=True)
class PythonAttempt(AbstractAsyncContextManager[None]):
    """Bound original operator waits while leaving the requested operation visible.

    Args:
        source: Caller-owned synchronous retry context.
    """

    source: AbstractContextManager[None]

    async def __aenter__(self) -> None:
        """Finish the original entry before the caller executes its operation."""
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._enter))
            await finish_legacy(task)

    def _enter(self) -> None:
        with LegacyControl():
            self.source.__enter__()

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Complete the original classification and wait before advancing.

        Args:
            kind: Original operation failure type.
            error: Original failure object.
            traceback: Original failure traceback.

        Returns:
            The original suppression decision.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._exit, kind, error, traceback)
            )
            return await finish_legacy(task)

    def _exit(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        with LegacyControl():
            return self.source.__exit__(kind, error, traceback)
