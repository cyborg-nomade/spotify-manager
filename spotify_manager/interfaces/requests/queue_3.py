"""Typed queue 3 inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from spotify_manager.application.ports.listening import RetryCall
    from spotify_manager.core.state.service import StateService
    from spotify_manager.routines.queue_3 import ComposerPlaylistReader
    from spotify_manager.routines.queue_3 import Echo
    from spotify_manager.routines.queue_3 import ProgressCallback
    from spotify_manager.routines.queue_3 import ReleaseTransitionReader

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class Queue3Options:
    """Specify the Queue 3 destination, import year and preview mode.

    Args:
        playlist_id: Playlist id.
        active_year: Active year.
        dry_run: Dry run.
    """

    playlist_id: str
    active_year: int | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class Queue3Callbacks:
    """Own release transitions, composer decisions and retry policy.

    Args:
        transition_reader: Transition reader.
        composer_playlist_reader: Composer playlist reader.
        echo: Echo.
        progress_callback: Progress callback.
        retry_call: Retry call.
    """

    transition_reader: ReleaseTransitionReader
    composer_playlist_reader: ComposerPlaylistReader | None = None
    echo: Echo = print
    progress_callback: ProgressCallback | None = None
    retry_call: RetryCall | None = None


@dataclass(frozen=True)
class Queue3Resources:
    """Identify yearly discoveries, checkpoint state and audit files.

    Args:
        state_path: State path.
        state_service: State service.
        log_path: Log path.
        albums_path: Albums path.
        removed_albums_log_path: Removed albums log path.
    """

    state_path: Path = FILES_DIR / "queue_3_state.json"
    state_service: StateService | None = None
    log_path: Path = FILES_DIR / "queue_3_log.jsonl"
    albums_path: Path = FILES_DIR / "albums_total_new.json"
    removed_albums_log_path: Path = FILES_DIR / "removed_albums_log.jsonl"
