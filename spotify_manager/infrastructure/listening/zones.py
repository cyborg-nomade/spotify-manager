"""Materialize explicit IANA calendar buckets without SQLite host-local time."""

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from threading import RLock

from spotify_manager.domain.listening_time import local_instant


def _zone_rows(
    source: sqlite3.Connection, timezone: str
) -> Iterator[tuple[int, str, int, int]]:
    for row in source.execute("SELECT DISTINCT ts FROM plays ORDER BY ts"):
        timestamp = int(row[0])
        instant = local_instant(timestamp, timezone)
        yield timestamp, instant.date().isoformat(), instant.weekday(), instant.hour


def listening_zone(path: Path, timezone: str, lock: RLock) -> Path:
    """Build at most one atomic timezone calendar table per ready generation.

    Args:
        path: Immutable history index.
        timezone: Validated IANA calendar timezone.
        lock: Generation-owned guard for concurrent first reads.

    Returns:
        A complete timezone database beside the history generation.

    Raises:
        OSError: Temporary tables cannot be published.
        sqlite3.Error: Materializing the calendar fails.
    """
    digest = hashlib.sha256(timezone.encode()).hexdigest()[:16]
    destination = path.with_suffix(f".{digest}.zone")
    with lock:
        if not destination.exists():
            _build_zone(path, destination, timezone)
    return destination


def _build_zone(source_path: Path, destination: Path, timezone: str) -> None:
    temporary = destination.with_suffix(".building")
    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute(
            "CREATE TABLE buckets "
            "(ts INTEGER PRIMARY KEY, day TEXT, weekday INT, hour INT)"
        )
        connection.executemany(
            "INSERT INTO buckets VALUES (?, ?, ?, ?)", _zone_rows(source, timezone)
        )
        connection.commit()
        connection.close()
        temporary.replace(destination)
    finally:
        source.close()
        connection.close()
        temporary.unlink(missing_ok=True)
