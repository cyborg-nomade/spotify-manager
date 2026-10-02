"""Compose canonical history refresh with its existing external boundaries."""

from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryReader
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.routines import scrobble_history as legacy


def _checked_at(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def refresh_history(
    lastfm: legacy.LastFmReader,
    expected_username: str | None,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    log_path: Path,
    dry_run: bool,
    full_rebuild: bool,
    now: datetime | None,
    progress_callback: legacy.ProgressCallback | None,
    cancel_check: legacy.CancelCheck | None,
) -> ScrobbleHistorySummary:
    """Wire the independent refresh workflow to caller-owned resources.

    Args:
        lastfm: Existing Last.fm client.
        expected_username: Optional ownership constraint.
        export_path: Canonical history file.
        legacy_delta_path: Optional legacy delta.
        backup_dir: Original backup destination.
        log_path: Original audit destination.
        dry_run: Suppress persistence effects.
        full_rebuild: Replace history from the entire API range.
        now: Optional effective refresh time.
        progress_callback: Optional presentation callback.
        cancel_check: Optional cancellation predicate.

    Returns:
        Original public summary with accepted effects.

    Raises:
        ScrobbleHistoryError: Validation or persistence fails.
        ScrobbleHistoryCancelledError: The caller requests cancellation.
    """
    storage = LegacyHistoryStorage(export_path, legacy_delta_path, backup_dir, log_path)
    workflow = HistoryRefresh(
        storage,
        LegacyHistoryReader(lastfm).fetch,
        partial(_checked_at, now),
        partial(legacy.check_cancel, cancel_check),
        partial(_progress, progress_callback),
    )
    return workflow.run(expected_username, dry_run, full_rebuild)
