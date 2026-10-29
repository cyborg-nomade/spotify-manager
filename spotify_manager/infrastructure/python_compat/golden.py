"""Retain synchronous Python golden resources at the outer compatibility edge."""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import spotify_manager.application.golden_selection as source_golden_selection
    import spotify_manager.routines.something_old as source_something_old


import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy
from spotify_manager.infrastructure.sync_compat import legacy_result


class BlockingGoldenArtistChoice(Protocol):
    """Caller-owned synchronous GoldenArtistChoice resource."""

    def choose_artist(
        self, artist: str, candidates: tuple[SpotifyArtistCandidate, ...], /
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
class PythonGoldenArtistChoice:
    """Await caller-owned GoldenArtistChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingGoldenArtistChoice | source_golden_selection.ArtistChoice

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_artist(
        self, artist: str, candidates: tuple[SpotifyArtistCandidate, ...], /
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
        self, artist: str, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_artist(artist, candidates)


class BlockingGoldenAlbumChoice(Protocol):
    """Caller-owned synchronous GoldenAlbumChoice resource."""

    def choose_album(
        self, artist: GoldenOldieArtist, candidates: tuple[DiscographyRelease, ...], /
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
class PythonGoldenAlbumChoice:
    """Await caller-owned GoldenAlbumChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingGoldenAlbumChoice | source_golden_selection.AlbumChoice

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_album(
        self, artist: GoldenOldieArtist, candidates: tuple[DiscographyRelease, ...], /
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
                asyncio.to_thread(self._blocking_choose_album, artist, candidates)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_album(
        self, artist: GoldenOldieArtist, candidates: tuple[DiscographyRelease, ...], /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_album(artist, candidates)


class BlockingListeningMode(Protocol):
    """Caller-owned synchronous ListeningMode resource."""

    def choose_mode(
        self, artist: GoldenOldieArtist, target: SpotifyArtistCandidate, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            target: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class PythonListeningMode:
    """Await caller-owned ListeningMode I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingListeningMode | source_something_old.ModeReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_mode(
        self, artist: GoldenOldieArtist, target: SpotifyArtistCandidate, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            target: Original interaction value.

        Returns:
            Original interaction result.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._blocking_choose_mode, artist, target)
            )
            value = await finish_legacy(task)
        return await legacy_result(value)

    def _blocking_choose_mode(
        self, artist: GoldenOldieArtist, target: SpotifyArtistCandidate, /
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_mode(artist, target)


class BlockingOldArtistChoice(Protocol):
    """Caller-owned synchronous OldArtistChoice resource."""

    def choose_artist(
        self,
        artist: GoldenOldieArtist,
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
class PythonOldArtistChoice:
    """Await caller-owned OldArtistChoice I/O at its original observation boundary.

    Args:
        source: Original synchronous or native async resource.
    """

    source: BlockingOldArtistChoice | source_something_old.ArtistChoiceReader

    def __bool__(self) -> bool:
        """Observe the caller's fallback choice without eagerly testing it.

        Returns:
            Original source truthiness.
        """
        return bool(self.source)

    async def choose_artist(
        self,
        artist: GoldenOldieArtist,
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
        artist: GoldenOldieArtist,
        candidates: tuple[SpotifyArtistCandidate, ...],
        /,
    ) -> str | Awaitable[str]:
        with LegacyControl():
            return self.source.choose_artist(artist, candidates)
