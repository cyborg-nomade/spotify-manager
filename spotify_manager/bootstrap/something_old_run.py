"""Compose Something Old's workflow with original caller-owned boundary inputs."""

from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.something_old_run import SomethingOld
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.infrastructure.legacy.something_old_run import LegacySomethingOld
from spotify_manager.routines import something_old as legacy


def run_something_old(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    playlist: str,
    username: str | None,
    mode_reader: legacy.ModeReader,
    album_reader: legacy.AlbumChoiceReader,
    artist_reader: legacy.ArtistChoiceReader | None,
    preview: bool,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    history_log_path: Path,
    log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall,
) -> SomethingOldSummary:
    """Bind original history, catalog, prompts, append and audit behavior.

    Args:
        spotify: Original caller-owned Spotify client.
        lastfm: Original caller-owned Last.fm reader.
        playlist: Original destination identity.
        username: Original expected history account.
        mode_reader: Original required mode presenter.
        album_reader: Original required studio-release presenter.
        artist_reader: Original optional exact-artist presenter.
        preview: Original preview behavior.
        export_path: Original canonical history location.
        legacy_delta_path: Original optional legacy delta location.
        backup_dir: Original history backup location.
        history_log_path: Original history audit location.
        log_path: Original selection audit location.
        now: Original optional timestamp.
        progress: Original optional progress presenter.
        retry: Original read-only retry boundary.

    Returns:
        Original complete selected, cancelled or nonempty summary.
    """
    edge = LegacySomethingOld(
        spotify,
        lastfm,
        playlist,
        username,
        mode_reader,
        album_reader,
        artist_reader,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        log_path,
        now,
        progress,
        retry,
    )
    return SomethingOld(edge, legacy.MIN_ARTIST_SCROBBLES).run(playlist, preview)
