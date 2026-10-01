"""Bind Something Old to original synchronous history, interaction and SDK seams."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import something_old as legacy


@dataclass(frozen=True)
class LegacySomethingOld:
    """Retain original caller-owned configuration, read-only retry and presenters.

    Args:
        spotify: Original caller-owned Spotify client.
        lastfm: Original caller-owned Last.fm reader.
        playlist: Original destination identity.
        username: Original expected history account.
        mode_reader: Original required mode presenter.
        album_reader: Original required studio-release presenter.
        artist_reader: Original optional exact-artist presenter.
        export_path: Original canonical history location.
        legacy_delta_path: Original optional legacy delta location.
        backup_dir: Original history backup location.
        history_log_path: Original history audit location.
        log_path: Original selection audit location.
        now: Original optional timestamp.
        callback: Original optional progress presenter.
        retry: Original read-only retry boundary.
    """

    spotify: Spotify
    lastfm: legacy.LastFmReader
    playlist: str
    username: str | None
    mode_reader: legacy.ModeReader
    album_reader: legacy.AlbumChoiceReader
    artist_reader: legacy.ArtistChoiceReader | None
    export_path: Path
    legacy_delta_path: Path | None
    backup_dir: Path
    history_log_path: Path
    log_path: Path
    now: datetime | None
    callback: legacy.ProgressCallback | None
    retry: legacy.RetryCall

    def clock(self) -> datetime:
        """Resolve the original timestamp before initial destination reads.

        Returns:
            Original supplied or current timestamp converted to UTC.
        """
        return (self.now or legacy.datetime.now(UTC)).astimezone(UTC)

    def progress(self, message: str) -> None:
        """Retain original optional progress presentation.

        Args:
            message: Original stage text.
        """
        if self.callback is not None:
            self.callback(message)

    def playlist_length(self, recheck: bool) -> int:
        """Read original destination authority with unchanged retry descriptions.

        Args:
            recheck: Whether this is the final pre-write empty-playlist guard.

        Returns:
            Original observed destination length.
        """
        description = (
            "rechecking Something Old before adding"
            if recheck
            else "checking whether Something Old is empty"
        )
        return legacy._load_playlist_state(
            self.spotify, self.playlist, self.retry, description
        ).total_items

    def history(self, now: datetime, preview: bool) -> ScrobbleHistorySummary:
        """Retain original refresh parameters and history publication behavior.

        Args:
            now: Original effective timestamp.
            preview: Original preview behavior.

        Returns:
            Original complete history refresh summary.
        """
        return legacy.scrobble_history.refresh_scrobble_history(
            self.lastfm,
            expected_username=self.username,
            export_path=self.export_path,
            legacy_delta_path=self.legacy_delta_path,
            backup_dir=self.backup_dir,
            log_path=self.history_log_path,
            dry_run=preview,
            now=now,
            progress_callback=self.callback,
        )

    def ranking(self, history: tuple[Scrobble, ...]) -> tuple[GoldenOldieArtist, ...]:
        """Retain the original configured Golden Oldies ranking seam.

        Args:
            history: Original refreshed history facts.

        Returns:
            Original ordered eligible artists.
        """
        return legacy.rank_golden_oldies(history)

    def resolve(self, artist: GoldenOldieArtist) -> SpotifyArtistCandidate | None:
        """Preserve original optional history-artist interaction adaptation.

        Args:
            artist: Original selected history artist.

        Returns:
            Original accepted mapping or cancellation.
        """
        reader = (
            partial(legacy._read_golden_artist_choice, self.artist_reader, artist)
            if self.artist_reader is not None
            else None
        )
        return legacy.resolve_spotify_artist(
            self.spotify, artist.artist, reader, self.retry
        )

    def mode(self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate) -> str:
        """Retain original mode interaction after accepting the artist.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original mode or cancellation text.
        """
        return self.mode_reader(artist, mapped)

    def lastfm_tracks(self, artist: GoldenOldieArtist) -> tuple[SelectedTrack, ...]:
        """Retain original strict Last.fm title resolution.

        Args:
            artist: Original selected history artist.

        Returns:
            Original ordered selected markers.
        """
        return legacy.select_lastfm_top_tracks(self.spotify, artist, self.retry)

    def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Retain original popular-track resolution and response validation.

        Args:
            artist: Original accepted Spotify mapping.

        Returns:
            Original ordered selected markers.
        """
        return legacy.select_spotify_top_tracks(self.spotify, artist, self.retry)

    def album_tracks(
        self,
        artist: GoldenOldieArtist,
        mapped: SpotifyArtistCandidate,
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        """Retain original studio-release interaction and complete track selection.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original release/markers or album-choice cancellation.
        """
        return legacy.select_album_tracks(
            self.spotify, artist, mapped, self.album_reader, self.retry
        )

    def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Accept the original complete selection without introducing write retries.

        Args:
            tracks: Original selected markers in source order.
        """
        legacy._add_tracks(self.spotify, self.playlist, tracks)

    def audit(self, summary: SomethingOldSummary) -> None:
        """Accept the original real-run completion audit after marker append.

        Args:
            summary: Original complete selected outcome.
        """
        legacy._append_log(summary, self.log_path)
