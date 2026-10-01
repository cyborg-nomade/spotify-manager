"""Pure Palace calendar eligibility and seconds-only historical album selection."""

from datetime import date
from datetime import datetime

from spotify_manager.domain.history import HistoricalAlbum
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import historical_album_offset
from spotify_manager.domain.history import rank_albums
from spotify_manager.domain.palace_values import HistoricalAlbumSelection


def cutoff(today: date) -> date:
    """Compute the original latest historical date from an explicit calendar fact.

    Args:
        today: Original effective local date.

    Returns:
        December 31 of the original previous calendar year.

    Raises:
        ValueError: The original date cannot represent a previous year.
    """
    return date(today.year - 1, 12, 31)


def dated_rankings(
    history: dict[date, list[Scrobble]],
    first: date,
    last: date,
) -> dict[date, tuple[HistoricalAlbum, ...]]:
    """Retain original nonempty album rankings within inclusive calendar bounds.

    Args:
        history: Original unordered complete dated scrobble buckets.
        first: Original inclusive earliest eligible date.
        last: Original inclusive latest historical date.

    Returns:
        Original qualifying ranked albums in bucket encounter order.
    """
    result = {}
    for day, scrobbles in history.items():
        if not first <= day <= last:
            continue
        ranked = rank_albums(scrobbles)
        if ranked:
            result[day] = ranked
    return result


def selected_albums(
    rankings: dict[date, tuple[HistoricalAlbum, ...]],
    indexes: tuple[int, ...],
    generated: datetime,
) -> tuple[HistoricalAlbumSelection, ...]:
    """Select original album ranks from sorted dates in supplied random index order.

    Args:
        rankings: Original eligible nonempty dated rankings.
        indexes: Original indexes, retaining custom-reader duplicates and ordering.
        generated: Original Random.org timestamp; only seconds choose album ranks.

    Returns:
        Original complete selected historical album facts.

    Raises:
        IndexError: The original custom reader supplies an out-of-range date index.
        ZeroDivisionError: A supplied ranking has no albums.
    """
    available = sorted(rankings)
    result = []
    for index in indexes:
        day = available[index]
        albums = rankings[day]
        offset = historical_album_offset(generated, len(albums))
        result.append(
            HistoricalAlbumSelection(
                day, index, len(albums), offset + 1, albums[offset]
            )
        )
    return tuple(result)
