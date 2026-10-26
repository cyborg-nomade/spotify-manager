"""Compose original release startup with caller-owned history and durable state."""

from datetime import datetime
from pathlib import Path

from spotify_manager.application.ports.runtime import ReviewProgressMessages
from spotify_manager.application.release_opening import ReleaseRunOpening
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.release_clock import ReleaseClock
from spotify_manager.infrastructure.legacy.release_opening import LegacyReleaseOpening
from spotify_manager.routines import release_check as legacy


def release_opening(
    lastfm: legacy.LastFmReader,
    expected_username: str | None,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    history_log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> tuple[ReleaseRunOpening, LegacyReleaseOpening]:
    """Construct release startup with caller-owned history and checkpoint resources.

    Args:
        lastfm: Caller-owned history reader.
        expected_username: Expected canonical history account.
        state_path: Existing namespace location.
        state_service: Optional shared state authority.
        log_path: Original release audit destination.
        export_path: Canonical history export.
        legacy_delta_path: Optional history delta.
        backup_dir: Original history backup location.
        history_log_path: Original history audit destination.
        now: Optional effective UTC timestamp.
        progress: Optional progress callback.

    Returns:
    The application opening stage and its state acquisition boundary.
    """
    effects = LegacyReleaseOpening(
        lastfm,
        expected_username,
        state_path,
        state_service,
        log_path,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        progress,
    )
    history_progress = None if progress is None else ReviewProgressMessages(progress)
    history = history_refresh(
        lastfm,
        export_path,
        legacy_delta_path,
        backup_dir,
        history_log_path,
        None,
        history_progress,
        None,
    )
    opening = ReleaseRunOpening(
        effects,
        history,
        expected_username,
        ReleaseClock(now),
        legacy.MIN_ARTIST_SCROBBLES,
    )
    return (opening, effects)
