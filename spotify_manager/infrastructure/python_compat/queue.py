"""Retain synchronous Python queue resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.queue_artist_mapping as queue_ports


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingQueueArtistChoice(Protocol):
    """Caller-owned synchronous QueueArtistChoice resource."""

    def choose_artist(
        self,
        artist: ArtistRecommendation,
        candidates: tuple[SpotifyArtistCandidate, ...],
        /,
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
class PythonQueueArtistChoice:
    """Await caller-owned QueueArtistChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingQueueArtistChoice | queue_ports.QueueArtistChoice

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_artist(
        self,
        artist: ArtistRecommendation,
        candidates: tuple[SpotifyArtistCandidate, ...],
        /,
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
                asyncio.to_thread(self._blocking_choose_artist, artist, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_artist(
        self,
        artist: ArtistRecommendation,
        candidates: tuple[SpotifyArtistCandidate, ...],
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_artist(artist, candidates)
