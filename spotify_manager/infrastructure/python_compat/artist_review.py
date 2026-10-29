"""Retain synchronous Python artist_review resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.artist_review_effects as artist_review_ports


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result
from spotify_manager.models.your_library import YourLibraryArtist


class BlockingArtistTrackChoice(Protocol):
    """Caller-owned synchronous ArtistTrackChoice resource."""

    def choose_track(
        self, artist: YourLibraryArtist, candidates: tuple[TrackCandidate, ...], /
    ) -> str:
        """Choose a track or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered tied candidates.

        Returns:
            Original selected identity or control response.
        """
        ...


@dataclass(frozen=True)
class PythonArtistTrackChoice:
    """Await caller-owned ArtistTrackChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingArtistTrackChoice | artist_review_ports.TrackChoices

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_track(
        self, artist: YourLibraryArtist, candidates: tuple[TrackCandidate, ...], /
    ) -> str:
        """Choose a track or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered tied candidates.

        Returns:
            Original selected identity or control response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_track, artist, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_track(
        self, artist: YourLibraryArtist, candidates: tuple[TrackCandidate, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_track(artist, candidates)


class BlockingArtistReleaseChoice(Protocol):
    """Caller-owned synchronous ArtistReleaseChoice resource."""

    def choose_release(
        self,
        artist: YourLibraryArtist,
        candidates: tuple[ReleaseCandidate, ...],
        allow_decline: bool,
        /,
    ) -> str:
        """Choose a release or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered release candidates.
            allow_decline: Whether declining is allowed at this stage.

        Returns:
            Original selected identity or control response.
        """
        ...


@dataclass(frozen=True)
class PythonArtistReleaseChoice:
    """Await caller-owned ArtistReleaseChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingArtistReleaseChoice | artist_review_ports.ReleaseChoices

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_release(
        self,
        artist: YourLibraryArtist,
        candidates: tuple[ReleaseCandidate, ...],
        allow_decline: bool,
        /,
    ) -> str:
        """Choose a release or return the original control response.

        Args:
            artist: Artist being reviewed.
            candidates: Ordered release candidates.
            allow_decline: Whether declining is allowed at this stage.

        Returns:
            Original selected identity or control response.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._blocking_choose_release, artist, candidates, allow_decline
                )
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_release(
        self,
        artist: YourLibraryArtist,
        candidates: tuple[ReleaseCandidate, ...],
        allow_decline: bool,
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_release(artist, candidates, allow_decline)
