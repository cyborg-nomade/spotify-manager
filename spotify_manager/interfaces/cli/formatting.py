"""Shared terminal date and file-size presentation."""

from datetime import datetime

from spotify_manager.interfaces.operations import blast_from_past


def format_file_size(size_bytes: int) -> str:
    """Format a byte count for a compact CLI summary.

    Args:
        size_bytes: Size bytes supplied by the caller.

    Returns:
        The original value selected or formatted by this adapter.
    """
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def scrobble_date(timestamp_ms: int) -> str:
    """Format a Last.fm timestamp in the original listening timezone.

    Args:
        timestamp_ms: Milliseconds since the Unix epoch.

    Returns:
        Original local calendar date text.
    """
    return datetime.fromtimestamp(
        timestamp_ms / 1000, blast_from_past.SCROBBLE_TIMEZONE
    ).strftime("%Y-%m-%d")
