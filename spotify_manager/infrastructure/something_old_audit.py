"""Preserve Something Old's original successful audit bytes and error translation."""

import json
from dataclasses import asdict
from pathlib import Path

from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.application.something_old_values import SomethingOldSummary


def append_log(summary: SomethingOldSummary, path: Path) -> None:
    """Append the original successful mutation record as UTF-8 JSON Lines.

    Args:
        summary: Original complete successful selection.
        path: Caller-owned audit location.

    Raises:
        SomethingOldError: The original audit cannot be appended.
    """
    record = {
        "generated_at": summary.generated_at.isoformat(),
        "playlist_id": summary.playlist_id,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "action": summary.action,
        "artist": asdict(summary.artist) if summary.artist else None,
        "spotify_artist": (
            asdict(summary.spotify_artist) if summary.spotify_artist else None
        ),
        "mode": summary.mode,
        "release": asdict(summary.release) if summary.release else None,
        "tracks": [asdict(track) for track in summary.tracks],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SomethingOldError(f"Could not write Something Old log: {path}") from exc
