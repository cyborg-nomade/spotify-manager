"""Refresh recommendation history through the injected history application workflow."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from spotify_manager.application.found_art_values import FoundArtStateError
from spotify_manager.application.history_values import ScrobbleHistoryError
from spotify_manager.domain.history import Scrobble
from spotify_manager.routines.found_art import LastFmReader


def refresh_history(
    lastfm: LastFmReader,
    *,
    export_path: Path,
    recent_path: Path,
    dry_run: bool,
    now: datetime | None,
    progress_callback: Callable[[str], None] | None,
) -> tuple[list[Scrobble], int]:
    """Read canonical history and retain recommendation-specific error translation.

    Args:
        lastfm: Caller-owned history reader.
        export_path: Canonical export location.
        recent_path: Recent history location.
        dry_run: Preserve the history workflow's preview semantics.
        now: Optional effective UTC time.
        progress_callback: Invocation-owned stage observer.

    Returns:
        Ordered canonical plays and the live-added count.

    Raises:
        FoundArtStateError: Canonical refresh fails, retaining its original cause.
    """
    from spotify_manager.bootstrap.history import history_refresh

    workflow = history_refresh(
        lastfm,
        export_path,
        recent_path,
        export_path.parent / "lastfm_history_backups",
        export_path.parent / "scrobble_history_update_log.jsonl",
        now,
        progress_callback,
        None,
    )
    try:
        summary = workflow.run(getattr(lastfm, "username", None), dry_run, False)
    except ScrobbleHistoryError as exc:
        raise FoundArtStateError(str(exc)) from exc
    return list(summary.history), summary.live_scrobbles_added
