"""Compose canonical history refresh with its existing external boundaries."""

from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryReader
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.routines import scrobble_history as legacy


def _checked_at(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def history_refresh(
    lastfm: legacy.LastFmReader,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    log_path: Path,
    now: datetime | None,
    progress_callback: legacy.ProgressCallback | None,
    cancel_check: legacy.CancelCheck | None,
) -> HistoryRefresh:
    """Construct the invocation dependencies without executing the use case.

    Args:
        lastfm: Existing Last.fm client.
        export_path: Canonical history file.
        legacy_delta_path: Optional legacy delta.
        backup_dir: Original backup destination.
        log_path: Original audit destination.
        now: Optional effective refresh time.
        progress_callback: Optional presentation callback.
        cancel_check: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.scrobble_history import check_cancel

    storage = LegacyHistoryStorage(export_path, legacy_delta_path, backup_dir, log_path)
    workflow = HistoryRefresh(
        storage,
        LegacyHistoryReader(lastfm).fetch,
        partial(_checked_at, now),
        partial(check_cancel, cancel_check),
        partial(_progress, progress_callback),
    )
    return workflow
