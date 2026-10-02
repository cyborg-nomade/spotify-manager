"""Decode original Queue cache records and append-only addition logs."""

import json
from collections.abc import Callable
from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from typing import cast

from spotify_manager.domain.queue_candidates import LastFmSimilarArtist


def _cache_timestamp(raw: dict[str, object]) -> datetime:
    timestamp = datetime.fromisoformat(str(raw["fetched_at"]))
    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp


def _neighbor(raw: dict[str, object]) -> LastFmSimilarArtist:
    return LastFmSimilarArtist(
        str(raw["artist"]), float(cast(float | str, raw["match"]))
    )


def cached_artists(
    raw: object,
    week: date,
    listening_week: Callable[[datetime], date],
) -> tuple[LastFmSimilarArtist, ...] | None:
    """Decode the original permissive current-week neighborhood record.

    Args:
        raw: Original unchecked cache entry.
        week: Original effective listening week.
        listening_week: Existing local-calendar boundary.

    Returns:
        Original observations, including empty hits, or a cache miss.

    Raises:
        OverflowError: Original numeric conversion overflows.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return _current_artists(raw, week, listening_week)
    except KeyError, TypeError, ValueError:
        return None


def _current_artists(
    raw: dict[str, object],
    week: date,
    listening_week: Callable[[datetime], date],
) -> tuple[LastFmSimilarArtist, ...] | None:
    if listening_week(_cache_timestamp(raw)) != week:
        return None
    values = raw["artists"]
    if not isinstance(values, list):
        return None
    artists: list[LastFmSimilarArtist] = []
    for value in values:
        if isinstance(value, dict):
            artists.append(_neighbor(value))
    return tuple(artists)


def _added_key(raw: object) -> str:
    if not isinstance(raw, dict) or raw.get("event") != "artist_added":
        return ""
    return str(raw.get("lastfm_artist_key") or "").strip()


def added_artist_keys(lines: Iterable[str]) -> set[str]:
    """Read actually added identities without treating preview events as additions.

    Args:
        lines: Original log lines in physical order.

    Returns:
        Original nonblank stripped keys, with duplicates collapsed.

    Raises:
        json.JSONDecodeError: An original nonblank line is malformed.
        OSError: The caller-owned stream cannot be read.
    """
    keys: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        key = _added_key(json.loads(line))
        if key:
            keys.add(key)
    return keys
