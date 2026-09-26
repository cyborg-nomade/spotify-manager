"""Shared legacy library record locations and local-period clock boundary."""

from datetime import datetime
from pathlib import Path


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
REMOVED_ALBUMS_LOG_PATH = FILES_DIR / "removed_albums_log.jsonl"


def current_stats_history_key(now: datetime | None = None) -> str:
    """Return the original local-date key used by statistics history.

    Args:
        now: Optional fixed timestamp; otherwise observe local time now.

    Returns:
        Year and zero-padded month with the original unpadded day.
    """
    current_time = now or datetime.now()
    month = (
        str(current_time.month)
        if current_time.month >= 10
        else f"0{current_time.month}"
    )
    return f"{current_time.year}.{month}.{current_time.day}"
