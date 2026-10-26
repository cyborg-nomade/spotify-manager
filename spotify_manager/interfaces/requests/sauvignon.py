"""Typed sauvignon inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotify_manager.infrastructure.output import STANDARD_OUTPUT


if TYPE_CHECKING:
    from datetime import datetime

    from spotify_manager.routines.sauvignon import AlbumChoiceReader
    from spotify_manager.routines.sauvignon import Echo
    from spotify_manager.routines.sauvignon import ProgressCallback
    from spotify_manager.routines.sauvignon import RetryCall

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class SauvignonOptions:
    """Specify the destination, recommendation limits and preview mode.

    Args:
        playlist_id: Playlist id.
        count: Count.
        max_playlist_length: Max playlist length.
        seed_count: Seed count.
        dry_run: Dry run.
        now: Now.
    """

    playlist_id: str
    count: int | None = None
    max_playlist_length: int | None = 20
    seed_count: int = 30
    dry_run: bool = False
    now: datetime | None = None


@dataclass(frozen=True)
class SauvignonCallbacks:
    """Own edition decisions, notifications and retry policy.

    Args:
        choice_reader: Choice reader.
        output: Echo.
        progress_callback: Progress callback.
        retry_call: Retry call.
    """

    choice_reader: AlbumChoiceReader | None
    output: Echo = STANDARD_OUTPUT
    progress_callback: ProgressCallback | None = None
    retry_call: RetryCall | None = None


@dataclass(frozen=True)
class SauvignonResources:
    """Identify history, recommendation cache and audit files.

    Args:
        export_path: Export path.
        recent_path: Recent path.
        cache_path: Cache path.
        log_path: Log path.
    """

    export_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    recent_path: Path = FILES_DIR / "found_art_recent_scrobbles.jsonl"
    cache_path: Path = FILES_DIR / "found_art_cache.json"
    log_path: Path = FILES_DIR / "sauvignon_recommendation_log.jsonl"
