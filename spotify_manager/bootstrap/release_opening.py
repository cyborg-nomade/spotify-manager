"""Compose original release startup with caller-owned history and durable state."""

from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.release_opening import ReleaseRunOpening
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.release_opening import LegacyReleaseOpening
from spotify_manager.routines import release_check as legacy


def _clock(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _local_date(stamp: datetime) -> date:
    return stamp.astimezone(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()


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
    from spotify_manager.routines.release_check import _run_id

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
    opening = ReleaseRunOpening(
        effects,
        partial(_clock, now),
        _local_date,
        _run_id,
        legacy.MIN_ARTIST_SCROBBLES,
    )
    return (opening, effects)
