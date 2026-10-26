"""Typed queue fill inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotify_manager.infrastructure.output import STANDARD_OUTPUT


if TYPE_CHECKING:
    from datetime import datetime

    from spotify_manager.core.state.service import StateService
    from spotify_manager.routines.the_queue import ArtistChoiceReader
    from spotify_manager.routines.the_queue import Echo
    from spotify_manager.routines.the_queue import ProgressCallback
    from spotify_manager.routines.the_queue import QueuePlaylists
    from spotify_manager.routines.the_queue import RetryCall

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class QueueFillOptions:
    """Specify Queue destinations, seed limits and preview mode.

    Args:
        playlists: Playlists.
        count: Count.
        max_playlist_length: Max playlist length.
        seed_count: Seed count.
        dry_run: Dry run.
        now: Now.
    """

    playlists: QueuePlaylists
    count: int | None = 20
    max_playlist_length: int | None = None
    seed_count: int = 30
    dry_run: bool = False
    now: datetime | None = None


@dataclass(frozen=True)
class QueueFillCallbacks:
    """Own artist decisions, notifications and retry policy.

    Args:
        choice_reader: Choice reader.
        output: Echo.
        progress_callback: Progress callback.
        retry_call: Retry call.
    """

    choice_reader: ArtistChoiceReader | None
    output: Echo = STANDARD_OUTPUT
    progress_callback: ProgressCallback | None = None
    retry_call: RetryCall | None = None


@dataclass(frozen=True)
class QueueFillResources:
    """Identify history, weekly state, cache and audit files.

    Args:
        export_path: Export path.
        recent_path: Recent path.
        state_path: State path.
        state_service: State service.
        cache_path: Cache path.
        log_path: Log path.
    """

    export_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    recent_path: Path = FILES_DIR / "found_art_recent_scrobbles.jsonl"
    state_path: Path = FILES_DIR / "queue_state.json"
    state_service: StateService | None = None
    cache_path: Path = FILES_DIR / "queue_recommendation_cache.json"
    log_path: Path = FILES_DIR / "queue_log.jsonl"
