"""Retain synchronous Python runtime resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.ports.runtime as source_runtime
    import spotify_manager.routines.analyse_library as source_analyse_library


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.library_analysis_values import RetryNotice
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingAnalysisWait(Protocol):
    """Caller-owned synchronous AnalysisWait resource."""

    def wait(self, notice: RetryNotice) -> bool:
        """Wait or request a clean pause using the original notice.

        Args:
            notice: Original retry status, attempt and delay.

        Returns:
            Whether the original request should continue.
        """
        ...


@dataclass(frozen=True)
class PythonAnalysisWait:
    """Await caller-owned AnalysisWait I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingAnalysisWait | source_analyse_library.RetryWait

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def wait(self, notice: RetryNotice) -> bool:
        """Wait or request a clean pause using the original notice.

        Args:
            notice: Original retry status, attempt and delay.

        Returns:
            Whether the original request should continue.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_wait, notice))
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_wait(self, notice: RetryNotice) -> bool | Awaitable[bool]:
        with LegacyControl():
            return self.source.wait(notice)


class BlockingWait(Protocol):
    """Caller-owned synchronous Wait resource."""

    def sleep(self, seconds: float) -> None:
        """Observe the original runtime boundary.

        Args:
            seconds: Original wait duration.
        """
        ...


@dataclass(frozen=True)
class PythonWait:
    """Await caller-owned Wait I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingWait | source_runtime.Wait

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def sleep(self, seconds: float) -> None:
        """Observe the original runtime boundary.

        Args:
            seconds: Original wait duration.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_sleep, seconds))
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_sleep(self, seconds: float) -> None | Awaitable[None]:
        with LegacyControl():
            return self.source.sleep(seconds)


class BlockingRandomIndexes(Protocol):
    """Caller-owned synchronous RandomIndexes resource."""

    def sample(self, population: int, count: int) -> RandomIndexSet:
        """Read indexes using the original external random source.

        Args:
            population: Eligible population size.
            count: Requested indexes.

        Returns:
            Original random index response.
        """
        ...


@dataclass(frozen=True)
class PythonRandomIndexes:
    """Await caller-owned RandomIndexes I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingRandomIndexes | source_runtime.RandomIndexes

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def sample(self, population: int, count: int) -> RandomIndexSet:
        """Read indexes using the original external random source.

        Args:
            population: Eligible population size.
            count: Requested indexes.

        Returns:
            Original random index response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_sample, population, count)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_sample(
        self, population: int, count: int
    ) -> RandomIndexSet | Awaitable[RandomIndexSet]:
        with LegacyControl():
            return self.source.sample(population, count)


class BlockingRandomTimestamp(Protocol):
    """Caller-owned synchronous RandomTimestamp resource."""

    def now(self) -> datetime:
        """Read the timestamp at the original external observation boundary.

        Returns:
            Original Random.org timestamp with its existing timezone semantics.
        """
        ...


@dataclass(frozen=True)
class PythonRandomTimestamp:
    """Await caller-owned RandomTimestamp I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingRandomTimestamp | source_runtime.RandomTimestampClock

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def now(self) -> datetime:
        """Read the timestamp at the original external observation boundary.

        Returns:
            Original Random.org timestamp with its existing timezone semantics.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_now))
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_now(self) -> datetime | Awaitable[datetime]:
        with LegacyControl():
            return self.source.now()
