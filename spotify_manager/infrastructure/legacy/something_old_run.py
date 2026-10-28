"""Bind Something Old to original synchronous history, interaction and SDK seams."""

import asyncio
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import something_old as legacy
from spotify_manager.routines.something_old import ArtistChoiceReader


@dataclass(frozen=True)
class LegacySomethingOld:
    """Bind application stages to caller-owned clients and storage.

    Args:
        spotify: Caller-owned spotify.
        lastfm: Caller-owned lastfm.
        options: Caller-owned options.
        callbacks: Caller-owned callbacks.
        resources: Caller-owned resources.
    """

    spotify: Spotify
    lastfm: legacy.LastFmReader
    options: SomethingOldOptions
    callbacks: SomethingOldCallbacks
    resources: SomethingOldResources

    def clock(self) -> datetime:
        """Resolve the original timestamp before initial destination reads.

        Returns:
            Original supplied or current timestamp converted to UTC.
        """
        return (self.options.now or legacy.datetime.now(UTC)).astimezone(UTC)

    def progress(self, message: str) -> None:
        """Retain original optional progress presentation.

        Args:
            message: Original stage text.
        """
        if self.callbacks.progress_callback is not None:
            self.callbacks.progress_callback.echo(message)

    async def playlist_length(self, recheck: bool) -> int:
        """Read original destination authority with unchanged retry descriptions.

        Args:
            recheck: Whether this is the final pre-write empty-playlist guard.

        Returns:
            Original observed destination length.
        """
        from spotify_manager.routines.something_old import _load_playlist_state

        description = (
            "rechecking Something Old before adding"
            if recheck
            else "checking whether Something Old is empty"
        )
        return (
            await _load_playlist_state(
                self.spotify,
                self.options.playlist_id,
                self.callbacks.retry_call,
                description,
            )
        ).total_items

    def ranking(self, history: tuple[Scrobble, ...]) -> tuple[GoldenOldieArtist, ...]:
        """Retain the original configured Golden Oldies ranking seam.

        Args:
            history: Original refreshed history facts.

        Returns:
            Original ordered eligible artists.
        """
        from spotify_manager.routines.something_old import rank_golden_oldies

        return rank_golden_oldies(history)

    async def resolve(self, artist: GoldenOldieArtist) -> SpotifyArtistCandidate | None:
        """Preserve original optional history-artist interaction adaptation.

        Args:
            artist: Original selected history artist.

        Returns:
            Original accepted mapping or cancellation.
        """
        from spotify_manager.routines.something_old import (
            async_resolve_spotify_artist as resolve_spotify_artist,
        )

        reader = (
            GoldenArtistChoice(self.callbacks.artist_choice_reader, artist)
            if self.callbacks.artist_choice_reader is not None
            else None
        )
        return await resolve_spotify_artist(
            self.spotify, artist.artist, reader, self.callbacks.retry_call
        )

    async def mode(
        self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate
    ) -> str:
        """Retain original mode interaction after accepting the artist.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original mode or cancellation text.
        """
        return await self.callbacks.mode_reader.choose_mode(artist, mapped)

    async def lastfm_tracks(
        self, artist: GoldenOldieArtist
    ) -> tuple[SelectedTrack, ...]:
        """Retain original strict Last.fm title resolution.

        Args:
            artist: Original selected history artist.

        Returns:
            Original ordered selected markers.
        """
        from spotify_manager.routines.something_old import (
            async_select_lastfm_top_tracks as select_lastfm_top_tracks,
        )

        return await select_lastfm_top_tracks(
            self.spotify, artist, self.callbacks.retry_call
        )

    async def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Retain original popular-track resolution and response validation.

        Args:
            artist: Original accepted Spotify mapping.

        Returns:
            Original ordered selected markers.
        """
        from spotify_manager.routines.something_old import (
            async_select_spotify_top_tracks as select_spotify_top_tracks,
        )

        return await select_spotify_top_tracks(
            self.spotify, artist, self.callbacks.retry_call
        )

    async def album_tracks(
        self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        """Retain original studio-release interaction and complete track selection.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original release/markers or album-choice cancellation.
        """
        from spotify_manager.routines.something_old import (
            async_select_album_tracks as select_album_tracks,
        )

        return await select_album_tracks(
            self.spotify,
            artist,
            mapped,
            self.callbacks.album_choice_reader,
            self.callbacks.retry_call,
        )

    async def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Accept the original complete selection without introducing write retries.

        Args:
            tracks: Original selected markers in source order.
        """
        from spotify_manager.routines.something_old import _add_tracks

        await _add_tracks(self.spotify, self.options.playlist_id, tracks)

    async def audit(self, summary: SomethingOldSummary) -> None:
        """Accept the original real-run completion audit after marker append.

        Args:
            summary: Original complete selected outcome.
        """
        from spotify_manager.routines.something_old import _append_log

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_append_log, summary, self.resources.log_path)
            )
            await finish_blocking(file_operation)


@dataclass(frozen=True)
class GoldenArtistChoice:
    """Keep the Golden Oldies evidence in an artist-search prompt.

    Args:
        reader: Original operator interaction.
        artist: Original selected historical artist.
    """

    reader: ArtistChoiceReader
    artist: GoldenOldieArtist

    async def choose_artist(
        self, name: str, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str:
        """Read the original artist prompt using its complete historical context.

        Args:
            name: Search label; historical evidence retains the original name.
            candidates: Original ordered search candidates.

        Returns:
            Original operator response.
        """
        return await self.reader.choose_artist(self.artist, candidates)
