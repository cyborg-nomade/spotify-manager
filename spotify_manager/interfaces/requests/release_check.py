"""Typed release check inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotify_manager.application.ports.runtime import NoRetry


if TYPE_CHECKING:
    from datetime import datetime

    from spotify_manager.core.state.service import StateService
    from spotify_manager.routines.release_check import ArtistChoiceReader
    from spotify_manager.routines.release_check import ProgressCallback
    from spotify_manager.routines.release_check import ReleaseCheckPlaylists
    from spotify_manager.routines.release_check import ReleaseChoiceReader
    from spotify_manager.routines.release_check import RetryCall

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class ReleaseCheckOptions:
    """Specify release destinations, history account and preview mode.

    Args:
        playlists: Playlists.
        expected_username: Expected username.
        dry_run: Dry run.
        now: Now.
    """

    playlists: ReleaseCheckPlaylists
    expected_username: str | None
    dry_run: bool = False
    now: datetime | None = None


@dataclass(frozen=True)
class ReleaseCheckCallbacks:
    """Own artist and release decisions, progress and retry policy.

    Args:
        artist_choice_reader: Artist choice reader.
        release_choice_reader: Release choice reader.
        progress_callback: Progress callback.
        retry_call: Retry call.
    """

    artist_choice_reader: ArtistChoiceReader | None = None
    release_choice_reader: ReleaseChoiceReader | None = None
    progress_callback: ProgressCallback | None = None
    retry_call: RetryCall = NoRetry()


@dataclass(frozen=True)
class ReleaseCheckResources:
    """Identify history, checkpoint state and release audit files.

    Args:
        state_path: State path.
        state_service: State service.
        log_path: Log path.
        export_path: Export path.
        legacy_delta_path: Legacy delta path.
        backup_dir: Backup dir.
        history_log_path: History log path.
    """

    state_path: Path = FILES_DIR / "release_check_state.json"
    state_service: StateService | None = None
    log_path: Path = FILES_DIR / "release_check_log.jsonl"
    export_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    legacy_delta_path: Path | None = FILES_DIR / "found_art_recent_scrobbles.jsonl"
    backup_dir: Path = FILES_DIR / "lastfm_history_backups"
    history_log_path: Path = FILES_DIR / "scrobble_history_update_log.jsonl"
