"""Read exact local-hour density over one pinned listening selection."""

from dataclasses import replace
from datetime import date
from functools import lru_cache
from typing import Protocol

from spotify_manager.application.listening_ports import ListeningMetadata
from spotify_manager.domain.listening_scrobble_map import MAX_POINT_DAYS
from spotify_manager.domain.listening_scrobble_map import MAX_POINTS
from spotify_manager.domain.listening_scrobble_map import HourPlayCount
from spotify_manager.domain.listening_scrobble_map import ListeningScrobbleMap
from spotify_manager.domain.listening_scrobble_map import build_scrobble_map
from spotify_manager.domain.listening_scrobble_map import build_scrobble_points
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ListeningQuery


class ScrobbleMapReads(Protocol):
    """Read indexed local-hours without exposing individual records to the map."""

    @property
    def metadata(self) -> ListeningMetadata:
        """Return the verified recorded history bounds."""
        ...

    def hourly_counts(self, query: ListeningQuery) -> tuple[HourPlayCount, ...]:
        """Return exact day and hour counts for the selected records."""
        ...

    def timestamps(self, query: ListeningQuery) -> tuple[int, ...]:
        """Return original recorded instants for a bounded detail selection."""
        ...


def _local_date(instant: int | None, timezone: str) -> date | None:
    return local_instant(instant, timezone).date() if instant is not None else None


@lru_cache(maxsize=8)
def get_scrobble_map(
    index: ScrobbleMapReads, query: ListeningQuery
) -> ListeningScrobbleMap:
    """Build the scrobble map and source coverage from one immutable generation.

    Args:
        index: Pinned indexed history resource.
        query: Exact date, timezone and artist or rhythm selection.

    Returns:
        Calendar columns and populated local-hour cells with their selected counts.
    """
    metadata = index.metadata
    bounds = (
        _local_date(metadata.first_ms, query.timezone),
        _local_date(metadata.last_ms, query.timezone),
    )
    result = build_scrobble_map(index.hourly_counts(query), query, bounds)
    if len(result.periods) <= MAX_POINT_DAYS and result.grain == "day":
        if result.plays <= MAX_POINTS:
            return replace(
                result, points=build_scrobble_points(index.timestamps(query), query)
            )
    return result
