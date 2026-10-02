"""Preserve majority-spelling artist rankings and historical date/seconds selection."""

from datetime import date
from datetime import datetime

from spotify_manager.domain.discography_values import HistoricalArtist
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check import rank_artists


def ranked_artists(scrobbles: list[Scrobble]) -> tuple[HistoricalArtist, ...]:
    """Rank normalized artists while retaining original majority display spellings.

    Args:
        scrobbles: Original ordered dated plays.

    Returns:
        Original descending-count, normalized-name artist ranking.
    """
    result = []
    for artist in rank_artists(tuple(scrobbles), 0):
        result.append(HistoricalArtist(artist.name, artist.scrobbles))
    return tuple(result)


def dated_artists(
    history: dict[date, list[Scrobble]],
    first: date,
    cutoff: date,
) -> dict[date, tuple[HistoricalArtist, ...]]:
    """Retain nonempty original artist-bearing dates within inclusive boundaries.

    Args:
        history: Original dated canonical plays.
        first: Original earliest eligible date.
        cutoff: Original latest eligible date.

    Returns:
        Original complete eligible rankings.
    """
    rankings = {}
    for day, plays in history.items():
        if not first <= day <= cutoff:
            continue
        ranked = ranked_artists(plays)
        if ranked:
            rankings[day] = ranked
    return rankings


def selected_artist(
    rankings: dict[date, tuple[HistoricalArtist, ...]],
    cutoff: date,
    index: int,
    generated: datetime,
) -> HistoricalArtistSelection:
    """Select the original date index and artist rank from the generated second.

    Args:
        rankings: Original eligible artist-bearing dates.
        cutoff: Original effective cutoff.
        index: Original supplied zero-based date index.
        generated: Original Random.org timestamp.

    Returns:
        Complete original date and one-based artist selection facts.

    Raises:
        IndexError: The original custom reader supplies an invalid date index.
    """
    dates = sorted(rankings)
    selected = dates[index]
    artists = rankings[selected]
    offset = generated.second % len(artists)
    return HistoricalArtistSelection(
        generated,
        cutoff,
        len(dates),
        selected,
        index,
        len(artists),
        offset + 1,
        artists[offset],
    )
