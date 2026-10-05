"""Bind Something Old to original synchronous history, interaction and SDK seams."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial

from spotipy import Spotify

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldResources
from spotify_manager.routines import something_old as legacy


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
            self.callbacks.progress_callback(message)

    def playlist_length(self, recheck: bool) -> int:
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
        return _load_playlist_state(
            self.spotify,
            self.options.playlist_id,
            self.callbacks.retry_call,
            description,
        ).total_items

    def history(self, now: datetime, preview: bool) -> ScrobbleHistorySummary:
        """Retain original refresh parameters and history publication behavior.

        Args:
            now: Original effective timestamp.
            preview: Original preview behavior.

        Returns:
            Original complete history refresh summary.
        """
        from spotify_manager.bootstrap.history import history_refresh

        workflow = history_refresh(
            self.lastfm,
            self.resources.export_path,
            self.resources.legacy_delta_path,
            self.resources.backup_dir,
            self.resources.history_log_path,
            now,
            self.callbacks.progress_callback,
            None,
        )
        return workflow.run(self.options.expected_username, preview, False)

    def ranking(self, history: tuple[Scrobble, ...]) -> tuple[GoldenOldieArtist, ...]:
        """Retain the original configured Golden Oldies ranking seam.

        Args:
            history: Original refreshed history facts.

        Returns:
            Original ordered eligible artists.
        """
        from spotify_manager.routines.something_old import rank_golden_oldies

        return rank_golden_oldies(history)

    def resolve(self, artist: GoldenOldieArtist) -> SpotifyArtistCandidate | None:
        """Preserve original optional history-artist interaction adaptation.

        Args:
            artist: Original selected history artist.

        Returns:
            Original accepted mapping or cancellation.
        """
        from spotify_manager.routines.something_old import _read_golden_artist_choice
        from spotify_manager.routines.something_old import resolve_spotify_artist

        reader = (
            partial(
                _read_golden_artist_choice, self.callbacks.artist_choice_reader, artist
            )
            if self.callbacks.artist_choice_reader is not None
            else None
        )
        return resolve_spotify_artist(
            self.spotify, artist.artist, reader, self.callbacks.retry_call
        )

    def mode(self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate) -> str:
        """Retain original mode interaction after accepting the artist.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original mode or cancellation text.
        """
        return self.callbacks.mode_reader(artist, mapped)

    def lastfm_tracks(self, artist: GoldenOldieArtist) -> tuple[SelectedTrack, ...]:
        """Retain original strict Last.fm title resolution.

        Args:
            artist: Original selected history artist.

        Returns:
            Original ordered selected markers.
        """
        from spotify_manager.routines.something_old import select_lastfm_top_tracks

        return select_lastfm_top_tracks(self.spotify, artist, self.callbacks.retry_call)

    def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Retain original popular-track resolution and response validation.

        Args:
            artist: Original accepted Spotify mapping.

        Returns:
            Original ordered selected markers.
        """
        from spotify_manager.routines.something_old import select_spotify_top_tracks

        return select_spotify_top_tracks(
            self.spotify, artist, self.callbacks.retry_call
        )

    def album_tracks(
        self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        """Retain original studio-release interaction and complete track selection.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original release/markers or album-choice cancellation.
        """
        from spotify_manager.routines.something_old import select_album_tracks

        return select_album_tracks(
            self.spotify,
            artist,
            mapped,
            self.callbacks.album_choice_reader,
            self.callbacks.retry_call,
        )

    def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Accept the original complete selection without introducing write retries.

        Args:
            tracks: Original selected markers in source order.
        """
        from spotify_manager.routines.something_old import _add_tracks

        _add_tracks(self.spotify, self.options.playlist_id, tracks)

    def audit(self, summary: SomethingOldSummary) -> None:
        """Accept the original real-run completion audit after marker append.

        Args:
            summary: Original complete selected outcome.
        """
        from spotify_manager.routines.something_old import _append_log

        _append_log(summary, self.resources.log_path)
