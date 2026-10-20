"""Typed something old inputs shared by HTTP and CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotify_manager.infrastructure.callbacks import call_direct


if TYPE_CHECKING:
    from datetime import datetime

    from spotify_manager.routines.something_old import AlbumChoiceReader
    from spotify_manager.routines.something_old import ArtistChoiceReader
    from spotify_manager.routines.something_old import ModeReader
    from spotify_manager.routines.something_old import ProgressCallback
    from spotify_manager.routines.something_old import RetryCall

FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class SomethingOldOptions:
    """Specify the empty destination, history account and preview mode.

    Args:
        playlist_id: Playlist id.
        expected_username: Expected username.
        dry_run: Dry run.
        now: Now.
    """

    playlist_id: str
    expected_username: str | None
    dry_run: bool = False
    now: datetime | None = None


@dataclass(frozen=True)
class SomethingOldCallbacks:
    """Own artist, listening-mode and album decisions.

    Args:
        mode_reader: Mode reader.
        album_choice_reader: Album choice reader.
        artist_choice_reader: Artist choice reader.
        progress_callback: Progress callback.
        retry_call: Retry call.
    """

    mode_reader: ModeReader
    album_choice_reader: AlbumChoiceReader
    artist_choice_reader: ArtistChoiceReader | None = None
    progress_callback: ProgressCallback | None = None
    retry_call: RetryCall = call_direct


@dataclass(frozen=True)
class SomethingOldResources:
    """Identify canonical history, backups and selection audits.

    Args:
        export_path: Export path.
        legacy_delta_path: Legacy delta path.
        backup_dir: Backup dir.
        history_log_path: History log path.
        log_path: Log path.
    """

    export_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    legacy_delta_path: Path | None = FILES_DIR / "found_art_recent_scrobbles.jsonl"
    backup_dir: Path = FILES_DIR / "lastfm_history_backups"
    history_log_path: Path = FILES_DIR / "scrobble_history_update_log.jsonl"
    log_path: Path = FILES_DIR / "something_old_log.jsonl"
