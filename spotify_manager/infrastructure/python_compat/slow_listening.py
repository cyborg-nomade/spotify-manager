"""Adapt synchronous Python Slow Listening decisions."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.slow_listening_values as listening_ports


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingReleaseOrder(Protocol):
    """Caller-owned synchronous ReleaseOrder resource."""

    def order_releases(
        self, date: str, releases: tuple[DiscographyRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            date: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonReleaseOrder:
    """Await caller-owned ReleaseOrder I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingReleaseOrder | listening_ports.ReleaseOrderReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def order_releases(
        self, date: str, releases: tuple[DiscographyRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            date: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_order_releases, date, releases)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_order_releases(
        self, date: str, releases: tuple[DiscographyRelease, ...], /
    ) -> tuple[str, ...] | Awaitable[tuple[str, ...]]:
        with LegacyControl():
            return self.source.order_releases(date, releases)


class BlockingListeningCompletion(Protocol):
    """Caller-owned synchronous ListeningCompletion resource."""

    def complete(self, source: PlaylistTrack, /) -> None:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonListeningCompletion:
    """Await caller-owned ListeningCompletion I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingListeningCompletion | listening_ports.CompletionNotifier

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def complete(self, source: PlaylistTrack, /) -> None:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_complete, source)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_complete(self, source: PlaylistTrack, /) -> None | Awaitable[None]:
        with LegacyControl():
            return self.source.complete(source)


class BlockingTrackAction(Protocol):
    """Caller-owned synchronous TrackAction resource."""

    def choose_track(
        self,
        source: PlaylistTrack,
        target: ReleaseTrack,
        release: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            target: Original interaction value.
            release: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonTrackAction:
    """Await caller-owned TrackAction I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingTrackAction | listening_ports.TrackActionReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_track(
        self,
        source: PlaylistTrack,
        target: ReleaseTrack,
        release: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            target: Original interaction value.
            release: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_track, source, target, release)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_track(
        self,
        source: PlaylistTrack,
        target: ReleaseTrack,
        release: DiscographyRelease,
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_track(source, target, release)
