"""Historical listening selection over explicit dates and random timestamps."""

import re
from collections import Counter
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Literal

from unidecode import unidecode


type Direction = Literal["top down", "bottom up"]


@dataclass(frozen=True)
class Scrobble:
    """One normalized Last.fm scrobble.

    Args:
        track: Original display title.
        artist: Original artist name.
        album: Original album name, possibly empty.
        timestamp_ms: Existing Unix timestamp in milliseconds.
    """

    track: str
    artist: str
    album: str
    timestamp_ms: int


@dataclass(frozen=True)
class ScrobbleSelection:
    """One date-to-scrobble selection with its rule trace.

    Args:
        selected_date: Chosen listening date.
        date_index: Original index in the eligible-date list.
        scrobbles_on_date: Total plays on that date.
        page: Selected one-based page number.
        total_pages: Number of populated pages.
        direction: Direction used within the selected page.
        position: One-based position in that direction.
        scrobble: Original selected play.
    """

    selected_date: date
    date_index: int
    scrobbles_on_date: int
    page: int
    total_pages: int
    direction: Direction
    position: int
    scrobble: Scrobble


@dataclass(frozen=True)
class HistoricalAlbum:
    """One album in a date's Last.fm ranking.

    Args:
        artist: First encountered display artist.
        album: First encountered display album name.
        scrobbles: Number of matched plays.
    """

    artist: str
    album: str
    scrobbles: int


def normalize_name(value: str) -> str:
    """Normalize accents and punctuation without retaining word boundaries.

    Args:
        value: Artist, album, or track title.

    Returns:
        Lowercase ASCII letters and digits, using the legacy Last.fm identity.
    """
    return re.sub(r"[^a-z0-9]+", "", unidecode(value).casefold())


def eligible_dates(
    history: Mapping[date, Sequence[Scrobble]],
    first_date: date,
    cutoff: date,
) -> list[date]:
    """Select populated dates inside the inclusive historical window.

    Args:
        history: Already-loaded scrobbles grouped by date.
        first_date: Earliest eligible day.
        cutoff: Latest eligible day.

    Returns:
        Eligible dates in chronological order.
    """
    result = []
    for day, scrobbles in history.items():
        if scrobbles and first_date <= day <= cutoff:
            result.append(day)
    return sorted(result)


def page_for_timestamp(generated_at: datetime, total_pages: int) -> int:
    """Map timestamp minutes and the legacy afternoon exception to a page.

    Args:
        generated_at: Random source timestamp, interpreted without timezone changes.
        total_pages: Number of populated Last.fm pages.

    Returns:
        Wrapped one-based page number.

    Raises:
        ValueError: There are no pages.
    """
    if total_pages < 1:
        raise ValueError("total_pages must be at least 1")
    minute = generated_at.minute
    if total_pages >= 7 and minute == 0 and generated_at.hour > 12:
        requested_page = 7
    else:
        first_minute_digit = minute // 10
        requested_page = 6 if first_minute_digit == 0 else first_minute_digit
    return ((requested_page - 1) % total_pages) + 1


def select_scrobble(
    selected_date: date,
    date_index: int,
    scrobbles: list[Scrobble],
    generated_at: datetime,
    page_size: int = 50,
) -> ScrobbleSelection:
    """Choose a historical track using page, direction, and wrapped seconds.

    Args:
        selected_date: Date selected by the random source.
        date_index: Original index of that date in the eligible date list.
        scrobbles: Scrobbles in their existing order on that date.
        generated_at: Random source timestamp.
        page_size: Existing Last.fm page size.

    Returns:
        Selected scrobble with the same one-based explanatory positions.

    Raises:
        ValueError: The date has no scrobbles.
        ZeroDivisionError: The supplied page size is zero.
    """
    if not scrobbles:
        raise ValueError("cannot select from a date without scrobbles")
    total_pages = (len(scrobbles) + page_size - 1) // page_size
    page = page_for_timestamp(generated_at, total_pages)
    start = (page - 1) * page_size
    ordered = scrobbles[start : start + page_size]
    direction: Direction = "top down" if generated_at.minute % 10 <= 4 else "bottom up"
    if direction == "bottom up":
        ordered = list(reversed(ordered))
    offset = generated_at.second % len(ordered)
    return ScrobbleSelection(
        selected_date,
        date_index,
        len(scrobbles),
        page,
        total_pages,
        direction,
        offset + 1,
        ordered[offset],
    )


def _album_key(scrobble: Scrobble) -> tuple[str, str] | None:
    if not scrobble.album.strip():
        return None
    key = (normalize_name(scrobble.artist), normalize_name(scrobble.album))
    return key if all(key) else None


def _rank_key(album: HistoricalAlbum) -> tuple[int, str, str]:
    return (-album.scrobbles, normalize_name(album.album), normalize_name(album.artist))


def rank_albums(scrobbles: Sequence[Scrobble]) -> tuple[HistoricalAlbum, ...]:
    """Rank albums by play count, retaining the first encountered spelling.

    Args:
        scrobbles: Ordered plays from one date, including blank album metadata.

    Returns:
        Albums sorted by descending count, then normalized album and artist names.
    """
    names: dict[tuple[str, str], tuple[str, str]] = {}
    counts: Counter[tuple[str, str]] = Counter()
    for scrobble in scrobbles:
        key = _album_key(scrobble)
        if key is None:
            continue
        names.setdefault(key, (scrobble.artist, scrobble.album))
        counts[key] += 1
    ranked = []
    for key, count in counts.items():
        ranked.append(HistoricalAlbum(names[key][0], names[key][1], count))
    return tuple(sorted(ranked, key=_rank_key))


def historical_album_offset(generated_at: datetime, album_count: int) -> int:
    """Select Palace's album rank using seconds only, independently of track paging.

    Args:
        generated_at: Random source timestamp.
        album_count: Number of ranked albums on the selected date.

    Returns:
        Zero-based wrapped rank.

    Raises:
        ZeroDivisionError: No albums are available.
    """
    return generated_at.second % album_count
