"""Read artist and album revisits from the immutable local calendar index."""

import sqlite3

from spotify_manager.domain.listening_rediscovery import ALBUM_OPTIONS
from spotify_manager.domain.listening_rediscovery import ArtistRevisitEvidence
from spotify_manager.domain.listening_rediscovery import RediscoveryDates
from spotify_manager.domain.listening_rediscovery import RevisitAlbum
from spotify_manager.domain.listening_time import listening_bounds
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.infrastructure.listening.sql import JOIN


def artist_revisit_counts(
    connection: sqlite3.Connection, dates: RediscoveryDates
) -> tuple[ArtistRevisitEvidence, ...]:
    """Count historical weeks and current engagement in local calendar buckets.

    Args:
        connection: Read-only history connection with an attached timezone calendar.
        dates: Two disjoint date windows.

    Returns:
        Counts for every artist present in the historical window.
    """
    sql = f"""
        WITH past AS (
            SELECT p.artist_id, COUNT(*) AS plays,
                   COUNT(DISTINCT date(b.day, '-' || b.weekday || ' days')) AS weeks
            {JOIN} WHERE p.ts>=? AND p.ts<? GROUP BY p.artist_id
        ), recent AS (
            SELECT p.artist_id, COUNT(*) AS plays, COUNT(DISTINCT b.day) AS days,
                   COUNT(DISTINCT p.track_id) AS tracks
            {JOIN} WHERE p.ts>=? AND p.ts<? GROUP BY p.artist_id
        )
        SELECT e.key, e.name, past.plays, past.weeks,
               COALESCE(recent.plays, 0), COALESCE(recent.days, 0),
               COALESCE(recent.tracks, 0)
        FROM past JOIN entities e ON e.id=past.artist_id
        LEFT JOIN recent ON recent.artist_id=past.artist_id
    """
    bounds = listening_bounds(dates.historical) + listening_bounds(dates.recent)
    return tuple(ArtistRevisitEvidence(*row) for row in connection.execute(sql, bounds))


def album_revisit_counts(
    connection: sqlite3.Connection, query: ListeningQuery, artist_keys: tuple[str, ...]
) -> dict[str, list[RevisitAlbum]]:
    """Read each shortlisted artist's most revisited historical albums.

    Args:
        connection: Read-only history connection with an attached timezone calendar.
        query: Historical dates and calendar timezone.
        artist_keys: Bounded shortlisted artist keys.

    Returns:
        Up to eight albums per artist, ordered by historical listening days.
    """
    if not artist_keys:
        return {}
    slots = ",".join("?" for _ in artist_keys)
    sql = f"""
        WITH albums AS (
            SELECT a.key AS artist, e.key AS album, e.name,
                   COUNT(DISTINCT b.day) AS days, COUNT(*) AS plays
            {JOIN} JOIN entities a ON a.id=p.artist_id
            JOIN entities e ON e.id=p.album_id
            WHERE p.ts>=? AND p.ts<? AND a.key IN ({slots})
            GROUP BY p.artist_id, p.album_id
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY artist ORDER BY days DESC, plays DESC, album
            ) AS position FROM albums
        )
        SELECT artist, album, name, days, plays FROM ranked
        WHERE position<=? ORDER BY artist, position
    """
    parameters = (*listening_bounds(query), *artist_keys, ALBUM_OPTIONS)
    result: dict[str, list[RevisitAlbum]] = {}
    for artist, album, name, days, plays in connection.execute(sql, parameters):
        result.setdefault(artist, []).append(RevisitAlbum(album, name, days, plays))
    return result
