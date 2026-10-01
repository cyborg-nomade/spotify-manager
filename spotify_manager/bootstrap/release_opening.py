"""Compose original release startup with caller-owned history and durable state."""

from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.release_opening import OpenedReleaseRun
from spotify_manager.application.release_opening import ReleaseRunOpening
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.release_opening import LegacyReleaseOpening
from spotify_manager.routines import release_check as legacy


def _clock(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _local_date(stamp: datetime) -> date:
    return stamp.astimezone(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()


def open_release_run(
    lastfm: legacy.LastFmReader,
    expected_username: str | None,
    dry_run: bool,
    state_path: Path,
    state_service: StateService | None,
    log_path: Path,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    history_log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> tuple[OpenedReleaseRun, RoutineState]:
    """Bind original clock, local date, history paths and accepted opening effects.

    Args:
        lastfm: Caller-owned history source.
        expected_username: Original canonical history ownership.
        dry_run: Original release preview mode.
        state_path: Original state location.
        state_service: Optional original shared service.
        log_path: Original release audit location.
        export_path: Original canonical history location.
        legacy_delta_path: Optional original delta location.
        backup_dir: Original history backup location.
        history_log_path: Original history audit location.
        now: Optional effective UTC timestamp.
        progress: Original progress observer.

    Returns:
        Original opening observations and the acquired original state handle.

    Raises:
        ReleaseCheckError: Original eligible ranking is empty.
        ReleaseCheckStateError: Original state or active window is unusable.
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
    opening = ReleaseRunOpening(
        effects,
        partial(_clock, now),
        _local_date,
        legacy._run_id,
        legacy.MIN_ARTIST_SCROBBLES,
    ).run(dry_run)
    return opening, effects.state_access
