"""Retain synchronous Python wine resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.new_wine_values as source_new_wine_values


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingWineReleaseChoice(Protocol):
    """Caller-owned synchronous WineReleaseChoice resource."""

    def choose_release(
        self, source: PlaylistTrack, candidates: tuple[ReleaseCandidate, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonWineReleaseChoice:
    """Await caller-owned WineReleaseChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingWineReleaseChoice | source_new_wine_values.ReleaseChoiceReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_release(
        self, source: PlaylistTrack, candidates: tuple[ReleaseCandidate, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_release, source, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_release(
        self, source: PlaylistTrack, candidates: tuple[ReleaseCandidate, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_release(source, candidates)


class BlockingWineEndpointChoice(Protocol):
    """Caller-owned synchronous WineEndpointChoice resource."""

    def choose_endpoint(
        self,
        source: PlaylistTrack,
        tracks: tuple[ReleaseTrack, ...],
        current_index: int,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            tracks: Original interaction value.
            current_index: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonWineEndpointChoice:
    """Await caller-owned WineEndpointChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingWineEndpointChoice | source_new_wine_values.EndpointChoiceReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_endpoint(
        self,
        source: PlaylistTrack,
        tracks: tuple[ReleaseTrack, ...],
        current_index: int,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            tracks: Original interaction value.
            current_index: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_choose_endpoint, source, tracks, current_index
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_endpoint(
        self,
        source: PlaylistTrack,
        tracks: tuple[ReleaseTrack, ...],
        current_index: int,
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_endpoint(source, tracks, current_index)
