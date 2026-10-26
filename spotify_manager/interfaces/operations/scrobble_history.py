"""Invoke scrobble history use cases for CLI and HTTP features."""

from datetime import datetime as datetime
from pathlib import Path as Path

from spotify_manager.application.history_values import (
    ScrobbleHistoryCancelledError as ScrobbleHistoryCancelledError,
)
from spotify_manager.application.history_values import (
    ScrobbleHistoryError as ScrobbleHistoryError,
)
from spotify_manager.application.history_values import (
    ScrobbleHistorySummary as ScrobbleHistorySummary,
)
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.routines.scrobble_history import (
    DEFAULT_BACKUP_DIR as DEFAULT_BACKUP_DIR,
)
from spotify_manager.routines.scrobble_history import (
    DEFAULT_LEGACY_DELTA_PATH as DEFAULT_LEGACY_DELTA_PATH,
)
from spotify_manager.routines.scrobble_history import (
    DEFAULT_LOG_PATH as DEFAULT_LOG_PATH,
)
from spotify_manager.routines.scrobble_history import (
    DEFAULT_SCROBBLES_PATH as DEFAULT_SCROBBLES_PATH,
)
from spotify_manager.routines.scrobble_history import CancelCheck as CancelCheck
from spotify_manager.routines.scrobble_history import LastFmReader as LastFmReader
from spotify_manager.routines.scrobble_history import (
    ProgressCallback as ProgressCallback,
)
from spotify_manager.routines.scrobble_history import check_cancel as check_cancel


def refresh_scrobble_history(
    lastfm: LastFmReader,
    *,
    expected_username: str | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    log_path: Path = DEFAULT_LOG_PATH,
    dry_run: bool = False,
    full_rebuild: bool = False,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> ScrobbleHistorySummary:
    """Merge recent plays, or replace all history from a complete API rebuild.

    Args:
        lastfm: Caller-owned reader for dated Last.fm tracks.
        expected_username: Optional export ownership constraint.
        export_path: Canonical export file.
        legacy_delta_path: Optional legacy Found Art delta.
        backup_dir: Destination for compressed original-history backups.
        log_path: Append-only refresh audit destination.
        dry_run: Suppress persistence while retaining observations.
        full_rebuild: Replace local history from the entire live API range.
        now: Optional effective refresh timestamp.
        progress_callback: Optional existing progress presenter.
        cancel_check: Optional predicate checked before expensive or mutating steps.

    Returns:
        Complete merged history and accepted persistence effects.

    Raises:
        ScrobbleHistoryError: Export validation, ownership or persistence fails.
        ScrobbleHistoryCancelledError: Cancellation is requested at a boundary.
    """
    configured = history_refresh(
        lastfm,
        export_path,
        legacy_delta_path,
        backup_dir,
        log_path,
        now,
        progress_callback,
        cancel_check,
    )
    return configured.run(expected_username, dry_run, full_rebuild)
