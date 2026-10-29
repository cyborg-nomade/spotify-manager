"""Retain synchronous Python release_check resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.artist_mapping as source_artist_mapping
    import spotify_manager.application.release_review as source_release_review


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingReleaseArtistChoice(Protocol):
    """Caller-owned synchronous ReleaseArtistChoice resource."""

    def choose_artist(
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...], /
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
class PythonReleaseArtistChoice:
    """Await caller-owned ReleaseArtistChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingReleaseArtistChoice | source_artist_mapping.ArtistChoiceReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_artist(
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...], /
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
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_artist(artist, candidates)


class BlockingReleaseChoice(Protocol):
    """Caller-owned synchronous ReleaseChoice resource."""

    def choose_release(
        self,
        artist: RankedArtist,
        release: ReleaseCandidate,
        track: ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            release: Original interaction value.
            track: Original interaction value.
            destinations: Original interaction value.
            unattached: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonReleaseChoice:
    """Await caller-owned ReleaseChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingReleaseChoice | source_release_review.ReleaseChoiceReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_release(
        self,
        artist: RankedArtist,
        release: ReleaseCandidate,
        track: ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            release: Original interaction value.
            track: Original interaction value.
            destinations: Original interaction value.
            unattached: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_choose_release,
                    artist,
                    release,
                    track,
                    destinations,
                    unattached,
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_release(
        self,
        artist: RankedArtist,
        release: ReleaseCandidate,
        track: ReleaseTrack,
        destinations: tuple[str, ...],
        unattached: bool,
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_release(
                artist, release, track, destinations, unattached
            )
