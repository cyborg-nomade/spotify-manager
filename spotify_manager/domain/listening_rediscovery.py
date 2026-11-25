"""Rank historical favorites by repeated listening and recent inactivity."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import Literal

from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ListeningQuery


REDISCOVERY_LIMIT = 20
ALBUM_OPTIONS = 8
PLAYLIST_ALBUM_LIMIT = 10

type RediscoveryHorizon = Literal[30, 90, 365]


class RediscoveryWindowError(ValueError):
    """Report a historical selection that overlaps the recent window."""


@dataclass(frozen=True)
class RediscoveryRules:
    """Set the recent horizon, historical window and minimum past listening."""

    recent_days: RediscoveryHorizon
    previous_year: bool
    minimum_plays: int
    minimum_weeks: int


@dataclass(frozen=True)
class RediscoveryDates:
    """Keep the two inclusive calendar windows and the available source bounds."""

    historical: ListeningQuery
    recent: ListeningQuery
    observed_from: date | None
    observed_through: date | None
    recent_complete: bool


@dataclass(frozen=True)
class ArtistRevisitEvidence:
    """Count historical plays and weeks, and recent days and distinct tracks."""

    key: str
    name: str
    historical_plays: int
    historical_weeks: int
    recent_plays: int
    recent_days: int
    recent_tracks: int


@dataclass(frozen=True)
class RevisitAlbum:
    """Describe a historical album and its number of recorded listening days."""

    key: str
    name: str
    days: int
    plays: int


@dataclass(frozen=True)
class RevisitAlbumChoice:
    """Pair a recorded album with published Spotify editions by exact name."""

    album: RevisitAlbum
    exact_editions: int
    spotify: LibraryEntry | None


@dataclass(frozen=True)
class ArtistRevisit:
    """Pair each qualifying artist with their historical album choices."""

    evidence: ArtistRevisitEvidence
    albums: tuple[RevisitAlbumChoice, ...]


@dataclass(frozen=True)
class ArtistRediscovery:
    """Present a bounded shortlist and enough window evidence to explain it."""

    dates: RediscoveryDates
    rules: RediscoveryRules
    library_snapshot: str | None
    albums_ready: bool
    qualifying: int
    artists: tuple[ArtistRevisit, ...]


def rediscovery_dates(
    query: ListeningQuery,
    rules: RediscoveryRules,
    source: tuple[int | None, int | None],
) -> RediscoveryDates:
    """Assign the recent window to the latest complete local source day.

    Args:
        query: Requested historical selection and timezone.
        rules: Historical mode and recent window length.
        source: First and last recorded UTC milliseconds.

    Returns:
        Non-overlapping windows and conservative observed date coverage.

    Raises:
        RediscoveryWindowError: The requested past period overlaps the recent window.
    """
    first_ms, last_ms = source
    first = _local_day(first_ms, query.timezone)
    last = _local_day(last_ms, query.timezone)
    last_complete = last - timedelta(days=1) if last else None
    recent_end = last_complete or query.end
    recent_start = recent_end - timedelta(days=rules.recent_days - 1)
    recent = ListeningQuery(recent_start, recent_end, query.timezone)
    historical = _historical_dates(query, rules, recent_start)
    complete = first is not None and first < recent_start and last_complete is not None
    return RediscoveryDates(historical, recent, first, last_complete, complete)


def _local_day(timestamp: int | None, timezone: str) -> date | None:
    return local_instant(timestamp, timezone).date() if timestamp is not None else None


def _historical_dates(
    query: ListeningQuery, rules: RediscoveryRules, recent_start: date
) -> ListeningQuery:
    if rules.previous_year:
        day = min(
            recent_start.day, monthrange(recent_start.year - 1, recent_start.month)[1]
        )
        start = recent_start.replace(year=recent_start.year - 1, day=day)
        return ListeningQuery(start, recent_start - timedelta(days=1), query.timezone)
    if query.end >= recent_start:
        raise RediscoveryWindowError(
            "End the historical period before the recent window starts."
        )
    return ListeningQuery(query.start, query.end, query.timezone)


def rank_rediscovery_artists(
    artists: tuple[ArtistRevisitEvidence, ...], rules: RediscoveryRules
) -> list[ArtistRevisitEvidence]:
    """Rank dormant artists ahead of light revisits, using historical weeks first.

    Args:
        artists: Counts in the two selected calendar windows.
        rules: Minimum past play and week thresholds.

    Returns:
        All qualifying artists, highest evidence first.
    """
    eligible = [artist for artist in artists if _qualifies(artist, rules)]
    return sorted(eligible, key=_rediscovery_order)


def _qualifies(artist: ArtistRevisitEvidence, rules: RediscoveryRules) -> bool:
    return (
        artist.historical_plays >= rules.minimum_plays
        and artist.historical_weeks >= rules.minimum_weeks
        and artist.recent_days <= 1
        and artist.recent_tracks <= 2
    )


def _rediscovery_order(artist: ArtistRevisitEvidence) -> tuple[bool, int, int, str]:
    return (
        artist.recent_plays > 0,
        -artist.historical_weeks,
        -artist.historical_plays,
        artist.key,
    )
