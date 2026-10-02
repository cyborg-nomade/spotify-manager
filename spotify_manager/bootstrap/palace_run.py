"""Compose Palace's application runner with original caller-owned resources."""

from datetime import date
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.palace_run import Palace
from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.palace_run import LegacyPalace
from spotify_manager.routines import palace_of_memory as legacy


def fill_palace(
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
    alphabetical_start: str | None,
    today: date | None,
    albums_path: Path,
    scrobbles_path: Path,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    album_backups_dir: Path,
    album_refresh_log_path: Path,
    random_index_reader: legacy.RandomIndexReader,
    retry_call: legacy.RetryCall | None,
    progress_callback: legacy.ProgressCallback | None,
    echo: legacy.Echo,
) -> PalaceOfMemorySummary:
    """Bind original live preflight, cursor authority, catalog, retries and presenters.

    Args:
        spotify: Original caller-owned client.
        playlist_id: Original destination identity.
        dry_run: Original preview behavior.
        alphabetical_start: Original optional manual reference.
        today: Original optional effective date.
        albums_path: Original canonical mirror location.
        scrobbles_path: Original history location.
        state_path: Original cursor location.
        state_service: Original optional shared state authority.
        log_path: Original completion audit location.
        album_backups_dir: Original mirror backup location.
        album_refresh_log_path: Original preflight audit location.
        random_index_reader: Original randomness boundary.
        retry_call: Original optional retry policy.
        progress_callback: Original optional stage presenter.
        echo: Original accepted-append presenter.

    Returns:
        Original complete selected and classified outcome.
    """
    retry = retry_call or legacy._direct_retry
    edge = LegacyPalace(
        spotify,
        playlist_id,
        today,
        albums_path,
        scrobbles_path,
        state_path,
        state_service,
        log_path,
        album_backups_dir,
        album_refresh_log_path,
        random_index_reader,
        retry,
        progress_callback,
        echo,
    )
    return Palace(edge, legacy.ALPHABETICAL_COUNT, legacy.ALBUM_MATCH_THRESHOLD).run(
        playlist_id,
        dry_run,
        alphabetical_start,
    )
