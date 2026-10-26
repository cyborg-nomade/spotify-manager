"""Typed palace inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotify_manager.infrastructure.output import STANDARD_OUTPUT
from spotify_manager.infrastructure.randomness import RANDOM_INDEXES


if TYPE_CHECKING:
    from datetime import date

    from spotify_manager.core.state.service import StateService
    from spotify_manager.routines.palace_of_memory import Echo
    from spotify_manager.routines.palace_of_memory import ProgressCallback
    from spotify_manager.routines.palace_of_memory import RandomIndexReader
    from spotify_manager.routines.palace_of_memory import RetryCall

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class PalaceOptions:
    """Specify the destination, calendar and optional cursor override.

    Args:
        playlist_id: Playlist id.
        dry_run: Dry run.
        alphabetical_start: Alphabetical start.
        today: Today.
    """

    playlist_id: str
    dry_run: bool = False
    alphabetical_start: str | None = None
    today: date | None = None


@dataclass(frozen=True)
class PalaceResources:
    """Identify the saved-album mirror, history, cursor and audits.

    Args:
        albums_path: Albums path.
        scrobbles_path: Scrobbles path.
        state_path: State path.
        state_service: State service.
        log_path: Log path.
        album_backups_dir: Album backups dir.
        album_refresh_log_path: Album refresh log path.
    """

    albums_path: Path = FILES_DIR / "albums_total_new.json"
    scrobbles_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    state_path: Path = FILES_DIR / "palace_of_memory_state.json"
    state_service: StateService | None = None
    log_path: Path = FILES_DIR / "palace_of_memory_log.jsonl"
    album_backups_dir: Path = FILES_DIR / "palace_of_memory_album_backups"
    album_refresh_log_path: Path = (
        FILES_DIR / "palace_of_memory_album_refresh_log.jsonl"
    )


@dataclass(frozen=True)
class PalaceCallbacks:
    """Own randomness, accepted-effect output and retry policy.

    Args:
        random_index_reader: Random index reader.
        retry_call: Retry call.
        progress_callback: Progress callback.
        output: Echo.
    """

    random_index_reader: RandomIndexReader = RANDOM_INDEXES
    retry_call: RetryCall | None = None
    progress_callback: ProgressCallback | None = None
    output: Echo = STANDARD_OUTPUT
