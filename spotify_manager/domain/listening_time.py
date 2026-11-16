"""Explicit timezone and identity rules for the Listening Explorer."""

import hashlib
import unicodedata
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from spotify_manager.domain.listening_values import ListeningQuery


def listening_identity(parts: tuple[str, ...]) -> str:
    """Create a stable analytics key without removing accents or punctuation.

    Args:
        parts: Ordered artist/title identity components.

    Returns:
        A deterministic hexadecimal key with component boundaries preserved.
    """
    digest = hashlib.sha256()
    for part in parts:
        normalized = unicodedata.normalize("NFC", part.strip()).casefold()
        encoded = normalized.encode("utf-8")
        digest.update(len(encoded).to_bytes(8))
        digest.update(encoded)
    return digest.hexdigest()


def local_instant(timestamp_ms: int, timezone: str) -> datetime:
    """Convert a recorded UTC timestamp to a selected display timezone.

    Args:
        timestamp_ms: Unix milliseconds.
        timezone: Valid IANA timezone name.

    Returns:
        An aware local datetime, including its DST fold.
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, ZoneInfo(timezone))


def listening_bounds(query: ListeningQuery) -> tuple[int, int]:
    """Map inclusive local dates to a half-open UTC interval.

    Args:
        query: Validated selection.

    Returns:
        Inclusive start and exclusive end in Unix milliseconds.
    """
    zone = ZoneInfo(query.timezone)
    start = datetime.combine(query.start, datetime.min.time(), zone)
    end = datetime.combine(query.end + timedelta(days=1), datetime.min.time(), zone)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def selected_rhythm(instant: datetime, query: ListeningQuery) -> bool:
    """Select a local hour/weekday without depending on the host timezone.

    Args:
        instant: Already converted local timestamp.
        query: Optional local rhythm selection.

    Returns:
        Whether the instant matches both rhythm filters.
    """
    if query.weekday is not None and instant.weekday() != query.weekday:
        return False
    return query.hour is None or instant.hour == query.hour


def hour_occurrences(
    query: ListeningQuery, coverage: tuple[int | None, int | None]
) -> dict[tuple[int, int], float]:
    """Count observed hours, including fractional boundaries and repeated DST hours.

    Args:
        query: Requested local interval.
        coverage: Earliest and latest recorded UTC milliseconds.

    Returns:
        Duration in hours for each covered local weekday/hour.
    """
    first, last = coverage
    counts: dict[tuple[int, int], float] = {}
    if first is None or last is None:
        return counts
    start, end = listening_bounds(query)
    cursor = max(start, first)
    end = min(end, last + 1)
    while cursor < end:
        instant = local_instant(cursor, query.timezone)
        boundary = min(end, _next_hour(cursor, instant))
        if selected_rhythm(instant, query):
            key = instant.weekday(), instant.hour
            counts[key] = counts.get(key, 0) + (boundary - cursor) / 3600000
        cursor = boundary
    return counts


def _next_hour(timestamp_ms: int, local: datetime) -> int:
    elapsed = ((local.minute * 60 + local.second) * 1000) + local.microsecond // 1000
    return timestamp_ms + 3600000 - elapsed


def bucket_name(day: date, grain: str) -> str:
    """Name a month or Monday-based week for a local listening date.

    Args:
        day: Local date.
        grain: Month or week.

    Returns:
        ISO date/month identifying the bucket start.
    """
    if grain == "week":
        return (day - timedelta(days=day.weekday())).isoformat()
    return day.isoformat()[:7]


def bucket_names(query: ListeningQuery, grain: str) -> tuple[str, ...]:
    """Include empty temporal buckets inside a selection.

    Args:
        query: Inclusive selected dates.
        grain: Month or week.

    Returns:
        Ordered unique bucket names.
    """
    names: dict[str, None] = {}
    day = query.start
    while day <= query.end:
        names[bucket_name(day, grain)] = None
        day += timedelta(days=1)
    return tuple(names)


def utc_iso(timestamp_ms: int | None) -> str | None:
    """Format an optional source timestamp for coverage displays.

    Args:
        timestamp_ms: Recorded Unix milliseconds or no observation.

    Returns:
        A UTC ISO timestamp or none.
    """
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, UTC).isoformat()
