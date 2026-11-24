"""Read exact bounded analytics from one immutable SQLite generation."""

import sqlite3
import unicodedata
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import RLock

from spotify_manager.application.listening_ports import ListeningEntityError
from spotify_manager.application.listening_ports import ListeningMetadata
from spotify_manager.domain.listening_scrobble_map import HourPlayCount
from spotify_manager.domain.listening_session_values import SessionWindow
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningCounts
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRanking
from spotify_manager.domain.listening_values import ListeningRecord
from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.infrastructure.listening.sql import COLUMNS
from spotify_manager.infrastructure.listening.sql import JOIN
from spotify_manager.infrastructure.listening.sql import lifetime_query
from spotify_manager.infrastructure.listening.sql import listening_where
from spotify_manager.infrastructure.listening.zones import listening_zone


class ListeningIndex:
    """Own one immutable generation and a bounded four-timezone calendar cache.

    Args:
        path: Completed SQLite history generation.
        metadata: Verified source and build metadata for that generation.
    """

    def __init__(self, path: Path, metadata: ListeningMetadata) -> None:
        """Bind immutable source identity and generation-owned timezone resources."""
        self.path = path
        self._metadata = metadata
        self._zone_lock = RLock()
        self._zones: OrderedDict[str, Path] = OrderedDict()

    @property
    def metadata(self) -> ListeningMetadata:
        """Return the generation's immutable verified source identity."""
        return self._metadata

    @contextmanager
    def connection(self, query: ListeningQuery) -> Iterator[sqlite3.Connection]:
        """Own a read-only connection and attach explicit local calendar buckets.

        Args:
            query: Selection whose validated timezone must be materialized.

        Yields:
            Connection closed after its query, including on failure.
        """
        with self._zone_lock:
            connection = self._open(query)
        try:
            yield connection
        finally:
            connection.close()

    def _open(self, query: ListeningQuery) -> sqlite3.Connection:
        zone = listening_zone(self.path, query.timezone, self._zone_lock)
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(
                "ATTACH DATABASE ? AS calendar", (zone.as_uri() + "?mode=ro",)
            )
        except sqlite3.Error:
            connection.close()
            raise
        self._zones[query.timezone] = zone
        self._zones.move_to_end(query.timezone)
        if len(self._zones) > 4:
            _old_timezone, old_path = self._zones.popitem(last=False)
            old_path.unlink(missing_ok=True)
        return connection

    def counts(
        self, query: ListeningQuery, selection: EntitySelection | None = None
    ) -> ListeningCounts:
        """Read exact counts, excluding missing albums only from unique-album totals.

        Args:
            query: Shared selection.
            selection: Optional independent detail entity.

        Returns:
            Exact recorded-row counts and selected UTC bounds.
        """
        where = listening_where(query, selection)
        sql = """SELECT COUNT(*), COUNT(DISTINCT artist_id),
            COUNT(DISTINCT track_id), COUNT(DISTINCT album_id),
            COUNT(DISTINCT b.day), COALESCE(SUM(album_id IS NULL), 0),
            MIN(p.ts), MAX(p.ts)"""
        with self.connection(query) as connection:
            row = connection.execute(
                sql + JOIN + where.sql, where.parameters
            ).fetchone()
        return ListeningCounts(*row)

    def timestamps(
        self, query: ListeningQuery, selection: EntitySelection | None = None
    ) -> tuple[int, ...]:
        """Read recorded instants without losing duplicate observations.

        Args:
            query: Shared selection.
            selection: Optional independent detail entity.

        Returns:
            Selected Unix timestamps in milliseconds.
        """
        where = listening_where(query, selection)
        with self.connection(query) as connection:
            rows = connection.execute(
                "SELECT p.ts" + JOIN + where.sql, where.parameters
            )
            return tuple(row[0] for row in rows)

    def hourly_counts(self, query: ListeningQuery) -> tuple[HourPlayCount, ...]:
        """Aggregate selected rows in the generation's existing local calendar.

        Args:
            query: Shared dates, timezone, artist and rhythm filters.

        Returns:
            Populated local days and hours, counting repeated source rows.
        """
        where = listening_where(query)
        sql = "SELECT b.day, b.hour, COUNT(*)" + JOIN + where.sql
        sql += " GROUP BY b.day, b.hour ORDER BY b.day, b.hour"
        result = []
        with self.connection(query) as connection:
            rows = connection.execute(sql, where.parameters)
            for row in rows:
                result.append(HourPlayCount(date.fromisoformat(row[0]), row[1], row[2]))
        return tuple(result)

    def rankings(
        self,
        query: ListeningQuery,
        options: RankingOptions,
        selection: EntitySelection | None = None,
    ) -> ListeningRanking:
        """Read bounded entity rankings with Unicode-aware name search.

        Args:
            query: Shared selection.
            options: Dimension, search, ordering, and page bounds.
            selection: Optional detail entity restricting related tracks.

        Returns:
            Ranked entities and the total matching names.
        """
        where = listening_where(query, selection)
        join = JOIN + f" JOIN entities e ON e.id=p.{COLUMNS[options.kind]}"
        search = unicodedata.normalize("NFC", options.search).casefold()
        predicate = where.sql + " AND instr(e.search, ?) > 0"
        parameters = where.parameters + (search,)
        order = (
            "COUNT(*) DESC, e.search, e.key"
            if options.order == "plays"
            else "e.search, e.key"
        )
        sql = "SELECT e.key, e.name, e.artist, COUNT(*)" + join + predicate
        sql += f" GROUP BY e.id ORDER BY {order} LIMIT ? OFFSET ?"
        with self.connection(query) as connection:
            total = connection.execute(
                "SELECT COUNT(DISTINCT e.id)" + join + predicate, parameters
            ).fetchone()[0]
            denominator = connection.execute(
                "SELECT COUNT(*)" + JOIN + where.sql, where.parameters
            ).fetchone()[0]
            rows = connection.execute(
                sql, parameters + (options.limit, (options.page - 1) * options.limit)
            )
            items = _ranked(rows, denominator)
        return ListeningRanking(items, total, options.page, options.limit)

    def artist_plays(
        self, query: ListeningQuery, *, full_history: bool = False
    ) -> tuple[ArtistPlay, ...]:
        """Read minimal observations for artist evolution or full-history cohorts.

        Args:
            query: Shared selection or cohort cutoff.
            full_history: Remove visible start and rhythm for first-observed history.

        Returns:
            Exact observations with stable artist/track identities.
        """
        effective = lifetime_query(query) if full_history else query
        where = listening_where(effective)
        join = (
            JOIN
            if effective.weekday is not None or effective.hour is not None
            else " FROM plays p "
        )
        sql = "SELECT p.ts, p.artist_id, p.track_id" + join
        with self.connection(effective) as connection:
            dimensions = _artist_dimensions(connection)
            rows = connection.execute(
                sql + where.sql + " ORDER BY p.ts, p.ordinal", where.parameters
            )
            return _artist_observations(rows, dimensions)

    def lifetimes(
        self, query: ListeningQuery, kind: EntityKind, *, full_history: bool = False
    ) -> tuple[EntityLifetime, ...]:
        """Read counts and bounds, optionally ignoring the visible start date.

        Args:
            query: Shared dates or lifetime analysis cutoff.
            kind: Fixed entity dimension.
            full_history: Read every recorded play before the cutoff.

        Returns:
            Entity counts and first/last recorded UTC instants.
        """
        effective = lifetime_query(query) if full_history else query
        where = listening_where(effective)
        sql = "SELECT e.key, e.name, e.artist, COUNT(*), MIN(p.ts), MAX(p.ts)" + JOIN
        sql += f" JOIN entities e ON e.id=p.{COLUMNS[kind]}"
        with self.connection(effective) as connection:
            rows = connection.execute(
                sql + where.sql + " GROUP BY e.id ORDER BY e.key", where.parameters
            )
            return tuple(EntityLifetime(*row) for row in rows)

    def entity_lifetime(
        self, query: ListeningQuery, selection: EntitySelection
    ) -> EntityLifetime:
        """Read an entity's pre-cutoff lifetime independently of the global artist.

        Args:
            query: Selected analysis cutoff and timezone.
            selection: Opened entity.

        Returns:
            Lifetime recorded facts.

        Raises:
            ListeningEntityError: The entity has no recorded play before the cutoff.
        """
        effective = replace(lifetime_query(query), artist=None)
        where = listening_where(effective, selection)
        sql = "SELECT e.key, e.name, e.artist, COUNT(*), MIN(p.ts), MAX(p.ts)" + JOIN
        sql += f" JOIN entities e ON e.id=p.{COLUMNS[selection.kind]}"
        with self.connection(effective) as connection:
            row = connection.execute(
                sql + where.sql + " GROUP BY e.id", where.parameters
            ).fetchone()
        if row is None:
            raise ListeningEntityError(
                "This entity has no recorded plays before the analysis date."
            )
        return EntityLifetime(*row)

    def records(
        self,
        query: ListeningQuery,
        options: RecordOptions,
    ) -> ListeningRecords:
        """Read original source names in stable newest-first pages.

        Args:
            query: Shared selection.
            options: One-based page, bounded size, and optional opened entity.

        Returns:
            Exact recorded observations and full filtered count.
        """
        where = listening_where(query, options.selection)
        sql = "SELECT p.ordinal, p.ts, a.key, p.artist, p.album, p.track" + JOIN
        sql += " JOIN entities a ON a.id=p.artist_id" + where.sql
        sql += " ORDER BY p.ts DESC, p.ordinal LIMIT ? OFFSET ?"
        parameters = where.parameters + (
            options.limit,
            (options.page - 1) * options.limit,
        )
        with self.connection(query) as connection:
            total = connection.execute(
                "SELECT COUNT(*)" + JOIN + where.sql, where.parameters
            ).fetchone()[0]
            rows = connection.execute(sql, parameters)
            items = tuple(ListeningRecord(*row) for row in rows)
        return ListeningRecords(items, total, options.page, options.limit)

    def session_records(
        self, query: ListeningQuery, window: SessionWindow, options: RecordOptions
    ) -> ListeningRecords:
        """Read only selected rows between this group's inclusive recorded bounds.

        Args:
            query: Exact dates and artist/rhythm selection used to form the group.
            window: First and last recorded UTC milliseconds, inclusive.
            options: Bounded chronological source-record page.

        Returns:
            Original rows ordered by timestamp, then source ordinal, and full count.
        """
        where = listening_where(query)
        predicate = where.sql + " AND p.ts>=? AND p.ts<=?"
        parameters = where.parameters + (window.first_ms, window.last_ms)
        sql = "SELECT p.ordinal, p.ts, a.key, p.artist, p.album, p.track" + JOIN
        sql += " JOIN entities a ON a.id=p.artist_id" + predicate
        sql += " ORDER BY p.ts, p.ordinal LIMIT ? OFFSET ?"
        page = (options.limit, (options.page - 1) * options.limit)
        with self.connection(query) as connection:
            total = connection.execute(
                "SELECT COUNT(*)" + JOIN + predicate, parameters
            ).fetchone()[0]
            rows = connection.execute(sql, parameters + page)
            items = tuple(ListeningRecord(*row) for row in rows)
        return ListeningRecords(items, total, options.page, options.limit)


def _ranked(rows: sqlite3.Cursor, total: int) -> tuple[RankedEntity, ...]:
    result = []
    for row in rows:
        share = row[3] / total if total else 0
        result.append(RankedEntity(row[0], row[1], row[2], row[3], share))
    return tuple(result)


def _artist_dimensions(connection: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    rows = connection.execute(
        "SELECT id, key, name FROM entities WHERE kind IN ('artist', 'track')"
    )
    result = {}
    for row in rows:
        result[row[0]] = (row[1], row[2])
    return result


def _artist_observations(
    rows: sqlite3.Cursor, dimensions: dict[int, tuple[str, str]]
) -> tuple[ArtistPlay, ...]:
    result = []
    for row in rows:
        key, name = dimensions[row[1]]
        result.append(ArtistPlay(row[0], key, name, dimensions[row[2]][0]))
    return tuple(result)
