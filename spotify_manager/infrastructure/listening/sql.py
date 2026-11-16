"""Parameterize listening filters while keeping SQL identifiers from fixed sets."""

from dataclasses import dataclass
from dataclasses import replace
from datetime import date

from spotify_manager.domain.listening_time import listening_bounds
from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningQuery


COLUMNS: dict[EntityKind, str] = {
    "artist": "artist_id",
    "album": "album_id",
    "track": "track_id",
}
JOIN = " FROM plays p JOIN calendar.buckets b ON b.ts=p.ts "


@dataclass(frozen=True)
class ListeningWhere:
    """Pair a fixed-structure SQL predicate with its separately bound values."""

    sql: str
    parameters: tuple[str | int, ...]


def listening_where(
    query: ListeningQuery, selection: EntitySelection | None = None
) -> ListeningWhere:
    """Bind dates, artist keys, rhythm, and an optional independent detail entity.

    Args:
        query: Validated shared filters.
        selection: Optional entity detail selection.

    Returns:
        SQL predicate and values, without interpolating user input into SQL.
    """
    start, end = listening_bounds(query)
    conditions = ["p.ts>=?", "p.ts<?"]
    parameters: list[str | int] = [start, end]
    if query.artist:
        conditions.append(
            "p.artist_id=(SELECT id FROM entities WHERE kind='artist' AND key=?)"
        )
        parameters.append(query.artist)
    if query.weekday is not None:
        conditions.append("b.weekday=?")
        parameters.append(query.weekday)
    if query.hour is not None:
        conditions.append("b.hour=?")
        parameters.append(query.hour)
    if selection is not None:
        conditions.append(
            f"p.{COLUMNS[selection.kind]}="
            "(SELECT id FROM entities WHERE kind=? AND key=?)"
        )
        parameters.extend((selection.kind, selection.key))
    return ListeningWhere(" WHERE " + " AND ".join(conditions), tuple(parameters))


def lifetime_query(query: ListeningQuery) -> ListeningQuery:
    """Retain the artist/cutoff but remove visible start and rhythm for lifetime facts.

    Args:
        query: Shared visible selection.

    Returns:
        Full recorded pre-cutoff selection.
    """
    return replace(query, start=date(1900, 1, 1), weekday=None, hour=None)
