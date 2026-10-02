"""Original matching history parsing, timestamp errors and local conversion."""

from collections.abc import Callable
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from typing import cast

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.scrobble_lookup_run import latest_history_timestamp
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.titles import without_sliding_qualifiers


def latest(
    load: Callable[[Path], dict[str, object]],
    path: Path,
    track: str,
    artist: str,
    timezone: tzinfo,
) -> datetime | None:
    """Read original history before matching and validating only relevant dates.

    Args:
        load: Original export fallback boundary.
        path: Original history location.
        track: Original resolved track name.
        artist: Original resolved primary artist.
        timezone: Original caller-owned timezone.

    Returns:
        Original latest matching play or none.

    Raises:
        LastFmExportError: An original row, matching date or final timestamp fails.
    """
    payload = load(path)
    rows = payload["scrobbles"]
    assert isinstance(rows, list)
    expected_track = normalize_name(without_sliding_qualifiers(track))
    expected_artist = normalize_name(artist)
    timestamp = latest_timestamp(rows, expected_track, expected_artist)
    if timestamp is None:
        return None
    return timestamp_time(timestamp, timezone)


def latest_timestamp(rows: list[object], track: str, artist: str) -> int | None:
    """Retain original row validation and latest-date encounter semantics.

    Args:
        rows: Original unchecked history rows.
        track: Original normalized title key.
        artist: Original normalized primary artist key.

    Returns:
        Original greatest matching timestamp or none.

    Raises:
        LastFmExportError: An original row or matching timestamp is invalid.
    """
    return latest_history_timestamp(rows, track, artist, checked_row, checked_timestamp)


def checked_row(raw: object, index: int) -> dict[str, object]:
    """Validate the original row container independently of matching.

    Args:
        raw: Original unchecked history row.
        index: Original raw row position.

    Returns:
        The same original mapping.

    Raises:
        LastFmExportError: The original row is not an object.
    """
    if not isinstance(raw, dict):
        raise LastFmExportError(f"Scrobble {index} is not an object.")
    return cast(dict[str, object], raw)


def checked_timestamp(row: dict[str, object], index: int) -> int:
    """Coerce the original matching date without tightening numeric acceptance.

    Args:
        row: Original matching row.
        index: Original raw position.

    Returns:
        Original coerced millisecond timestamp.

    Raises:
        LastFmExportError: Original date indexing or integer conversion fails.
    """
    try:
        return int(cast(int | str, row["date"]))
    except (KeyError, TypeError, ValueError) as error:
        raise LastFmExportError(
            f"Scrobble {index} has no valid millisecond timestamp."
        ) from error


def timestamp_time(timestamp: int, timezone: tzinfo) -> datetime:
    """Convert the original greatest timestamp after the entire matching scan.

    Args:
        timestamp: Original greatest millisecond timestamp.
        timezone: Original local timezone.

    Returns:
        Original local observation time.

    Raises:
        LastFmExportError: The original final timestamp is out of range.
    """
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone)
    except (OSError, OverflowError, ValueError) as error:
        raise LastFmExportError(
            "The latest matching scrobble has an out-of-range timestamp."
        ) from error
