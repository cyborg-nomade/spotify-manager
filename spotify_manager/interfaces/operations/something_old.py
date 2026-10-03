"""Invoke something old use cases for CLI and HTTP features."""

from datetime import datetime as datetime
from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.something_old_values import (
    SomethingOldConfigError as SomethingOldConfigError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldError as SomethingOldError,
)
from spotify_manager.application.something_old_values import (
    SomethingOldSummary as SomethingOldSummary,
)
from spotify_manager.bootstrap.something_old_run import something_old
from spotify_manager.domain.golden_oldies import GoldenOldieArtist as GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack as SelectedTrack
from spotify_manager.domain.golden_selection import (
    SpotifyArtistCandidate as SpotifyArtistCandidate,
)
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines.something_old import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.something_old import (
    AlbumChoiceReader as AlbumChoiceReader,
)
from spotify_manager.routines.something_old import (
    ArtistChoiceReader as ArtistChoiceReader,
)
from spotify_manager.routines.something_old import LastFmReader as LastFmReader
from spotify_manager.routines.something_old import ModeReader as ModeReader
from spotify_manager.routines.something_old import ProgressCallback as ProgressCallback
from spotify_manager.routines.something_old import RetryCall as RetryCall
from spotify_manager.routines.something_old import _direct_retry as _direct_retry
from spotify_manager.routines.something_old import (
    parse_playlist_id as parse_playlist_id,
)


def run_something_old(
    sp: Spotify,
    lastfm: LastFmReader,
    playlist_id: str,
    *,
    expected_username: str | None,
    mode_reader: ModeReader,
    album_choice_reader: AlbumChoiceReader,
    artist_choice_reader: ArtistChoiceReader | None = None,
    dry_run: bool = False,
    export_path: Path = scrobble_history.DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = scrobble_history.DEFAULT_BACKUP_DIR,
    history_log_path: Path = scrobble_history.DEFAULT_LOG_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall = _direct_retry,
) -> SomethingOldSummary:
    """Refresh history and fill an empty Something Old playlist cautiously.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history reader.
        playlist_id: Original destination identity.
        expected_username: Original expected Last.fm account.
        mode_reader: Original recipe interaction.
        album_choice_reader: Original studio-release interaction.
        artist_choice_reader: Optional original exact-artist ambiguity interaction.
        dry_run: Original preview behavior, including history refresh semantics.
        export_path: Original canonical history location.
        legacy_delta_path: Original optional history delta location.
        backup_dir: Original history backup directory.
        history_log_path: Original history refresh audit location.
        log_path: Original successful selection audit location.
        now: Original optional effective timestamp.
        progress_callback: Original optional stage presenter.
        retry_call: Original read retry policy.

    Returns:
        Original complete selected, cancelled or nonempty outcome.

    Raises:
        SomethingOldError: Original history, selection, authority or audit fails.
    """
    configured = something_old(
        sp,
        lastfm,
        playlist_id,
        expected_username,
        mode_reader,
        album_choice_reader,
        artist_choice_reader,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        log_path,
        now,
        progress_callback,
        retry_call,
    )
    return configured.run(playlist_id, dry_run)
