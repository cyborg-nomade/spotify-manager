"""Retain synchronous Python queue_3 resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.queue_3_composers as source_queue_3_composers
    import spotify_manager.application.queue_3_planner as source_queue_3_planner


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingQueueTransition(Protocol):
    """Caller-owned synchronous QueueTransition resource."""

    def choose_transition(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            current: Original interaction value.
            following: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonQueueTransition:
    """Await caller-owned QueueTransition I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingQueueTransition | source_queue_3_planner.TransitionReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_transition(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            current: Original interaction value.
            following: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_choose_transition, source, current, following
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_transition(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_transition(source, current, following)


class BlockingComposerChoice(Protocol):
    """Caller-owned synchronous ComposerChoice resource."""

    def choose_composer(
        self, artist: str, candidates: tuple[OwnedPlaylist, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonComposerChoice:
    """Await caller-owned ComposerChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingComposerChoice | source_queue_3_composers.ComposerReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_composer(
        self, artist: str, candidates: tuple[OwnedPlaylist, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_composer, artist, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_composer(
        self, artist: str, candidates: tuple[OwnedPlaylist, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_composer(artist, candidates)
