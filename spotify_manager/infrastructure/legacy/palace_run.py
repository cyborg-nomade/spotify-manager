"""Bind Palace's application stages to original synchronous compatibility seams."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_effects import PalaceStateAccess
from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.palace_values import HistoricalAlbumSelection
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import palace_of_memory as legacy


@dataclass(frozen=True)
class LegacyPalace:
    """Retain caller-owned synchronous resources and original configuration.

    Args:
        spotify: Original caller-owned client.
        playlist_id: Original destination identity.
        today: Original optional effective date.
        albums_path: Original canonical mirror location.
        scrobbles_path: Original history location.
        state_path: Original cursor location.
        state_service: Original optional shared authority.
        log_path: Original completion audit location.
        backups_dir: Original mirror backup directory.
        refresh_log: Original mirror preflight audit location.
        random_reader: Original Random.org boundary.
        retry: Original retry policy, including append retry behavior.
        callback: Original optional stage presenter.
        output: Original accepted-append presenter.
    """

    spotify: Spotify
    playlist_id: str
    today: date | None
    albums_path: Path
    scrobbles_path: Path
    state_path: Path
    state_service: StateService | None
    log_path: Path
    backups_dir: Path
    refresh_log: Path
    random_reader: legacy.RandomIndexReader
    retry: legacy.RetryCall
    callback: legacy.ProgressCallback | None
    output: legacy.Echo

    def progress(self, message: str) -> None:
        """Retain original optional progress delivery.

        Args:
            message: Original visible stage.
        """
        if self.callback is not None:
            self.callback(message)

    def refresh(self) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
        """Retain original live mirror preflight and publication even in preview.

        Returns:
            Original complete mirror and refresh result.
        """
        from spotify_manager.bootstrap.palace_mirror import saved_mirror

        workflow = saved_mirror(
            self.spotify,
            self.albums_path,
            self.backups_dir,
            self.refresh_log,
            self.retry,
            self.callback,
        )
        return workflow.run()

    def state_access(self) -> PalaceStateAccess:
        """Resolve original shared authority or explicit legacy path.

        Returns:
            Original caller-owned state boundary.
        """
        from spotify_manager.routines.palace_of_memory import _state_access

        return _state_access(self.state_path, self.state_service)

    def start_index(
        self,
        albums: tuple[YourLibraryAlbum, ...],
        manual: str | None,
        state: dict[str, object],
    ) -> int:
        """Retain original reference parsing and durable cursor validation.

        Args:
            albums: Original refreshed mirror.
            manual: Original optional manual override.
            state: Original loaded namespace.

        Returns:
            Original selected zero-based position.
        """
        from spotify_manager.routines.palace_of_memory import _cursor_index
        from spotify_manager.routines.palace_of_memory import resolve_alphabetical_start

        if manual is not None:
            return resolve_alphabetical_start(albums, manual)
        return _cursor_index(state, albums)

    def historical(
        self,
    ) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
        """Retain original history loading, cutoff and Random.org semantics.

        Returns:
            Original effective time, cutoff, eligible count and selections.
        """
        from spotify_manager.bootstrap.palace_history import palace_history

        workflow = palace_history(
            self.scrobbles_path, self.today, self.random_reader, self.callback
        )
        return workflow.run(legacy.HISTORY_COUNT)

    def playlist(self, recheck: bool) -> PlaylistState:
        """Read original destination authority through the original retry boundary.

        Args:
            recheck: Whether this is the final pre-write check.

        Returns:
            Original valid complete live facts.
        """
        from spotify_manager.routines.palace_of_memory import _read_palace_playlist

        return _read_palace_playlist(
            self.spotify, self.playlist_id, self.retry, recheck
        )

    def first_track(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Read the original first playable marker.

        Args:
            album: Original resolved release.

        Returns:
            Original complete first marker.
        """
        from spotify_manager.routines.palace_of_memory import load_first_track

        return load_first_track(self.spotify, album, self.retry)

    def search(self, artist: str, album: str) -> SpotifyAlbum | None:
        """Retain original historical album qualification and search options.

        Args:
            artist: Original expected artist spelling.
            album: Original expected title.

        Returns:
            Original qualified remote release or none.
        """
        from spotify_manager.routines.palace_of_memory import search_spotify_album

        return search_spotify_album(self.spotify, artist, album, self.retry)

    def append(self, pending: tuple[SpotifyFirstTrack, ...]) -> None:
        """Retain the original caller-owned retry around complete marker append.

        Args:
            pending: Original ordered distinct first tracks.
        """
        from spotify_manager.routines.palace_of_memory import _append_first_tracks

        _append_first_tracks(self.spotify, self.playlist_id, pending, self.retry)

    def echo(self, message: str) -> None:
        """Retain original accepted-write presentation.

        Args:
            message: Original completion text.
        """
        self.output(message)

    def cursor_payload(
        self, next_index: int, last: YourLibraryAlbum
    ) -> dict[str, object]:
        """Build the original complete cursor replacement with a fresh write clock.

        Args:
            next_index: Original next position.
            last: Original last selected saved album.

        Returns:
            Original complete checkpoint fields.
        """
        from spotify_manager.routines.palace_of_memory import _cursor_payload

        return _cursor_payload(next_index, last)

    def audit(self, summary: PalaceOfMemorySummary) -> None:
        """Retain original completion audit after the successful cursor checkpoint.

        Args:
            summary: Original complete selected outcome.
        """
        from spotify_manager.routines.palace_of_memory import _append_log

        _append_log(self.log_path, summary)
