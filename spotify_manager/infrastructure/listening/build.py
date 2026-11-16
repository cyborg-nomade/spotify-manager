"""Validate every source observation before publishing a complete SQLite index."""

import json
import sqlite3
import time
import unicodedata
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import cast

from spotify_manager.application.listening_ports import ListeningMetadata
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.domain.listening_time import listening_identity


INDEX_VERSION = "v1"
SCHEMA = """
CREATE TABLE entities (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL,
    name TEXT NOT NULL, artist TEXT NOT NULL, search TEXT NOT NULL, UNIQUE(kind, key)
);
CREATE TABLE plays (
    ordinal INTEGER PRIMARY KEY, ts INTEGER NOT NULL,
    artist_id INTEGER NOT NULL, album_id INTEGER, track_id INTEGER NOT NULL,
    artist TEXT NOT NULL, album TEXT NOT NULL, track TEXT NOT NULL,
    source_album_id TEXT NOT NULL
);
CREATE TABLE metadata (document TEXT NOT NULL);
"""
INDEXES = """
CREATE INDEX plays_time ON plays(ts);
CREATE INDEX plays_artist ON plays(artist_id, ts);
CREATE INDEX plays_album ON plays(album_id, ts);
CREATE INDEX plays_track ON plays(track_id, ts);
ANALYZE;
"""


@dataclass(frozen=True)
class _SourceRow:
    timestamp: int
    artist: str
    album: str
    track: str
    album_id: str


def _text(row: dict[str, object], key: str, *, required: bool = False) -> str:
    value = row.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"Last.fm {key} must be a nonempty string.")
    return value


def _source_row(raw: object, ordinal: int) -> _SourceRow:
    if not isinstance(raw, dict):
        raise ValueError(f"Last.fm row {ordinal} must be an object.")
    row = cast(dict[str, object], raw)
    timestamp = row.get("date")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        raise ValueError(f"Last.fm row {ordinal} must have integer milliseconds.")
    if not 0 <= timestamp < 4102444800000:
        raise ValueError(f"Last.fm row {ordinal} has an out-of-range date.")
    return _SourceRow(
        timestamp,
        _text(row, "artist", required=True),
        _text(row, "album"),
        _text(row, "track", required=True),
        _text(row, "albumId"),
    )


@dataclass
class _IndexWriter:
    connection: sqlite3.Connection
    entities: dict[tuple[str, str], int] = field(default_factory=dict)

    def entity(self, kind: str, name: str, artist: str) -> int:
        parts = (name,) if kind == "artist" else (artist, name)
        key = listening_identity(parts)
        identity = kind, key
        existing = self.entities.get(identity)
        if existing is not None:
            return existing
        identifier = len(self.entities) + 1
        self.connection.execute(
            "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?)",
            (
                identifier,
                kind,
                key,
                name.strip(),
                artist.strip(),
                unicodedata.normalize("NFC", name + " " + artist).casefold(),
            ),
        )
        self.entities[identity] = identifier
        return identifier

    def add(self, raw: object, ordinal: int) -> None:
        row = _source_row(raw, ordinal)
        artist = self.entity("artist", row.artist, row.artist)
        album = (
            self.entity("album", row.album, row.artist) if row.album.strip() else None
        )
        track = self.entity("track", row.track, row.artist)
        self.connection.execute(
            "INSERT INTO plays VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ordinal,
                row.timestamp,
                artist,
                album,
                track,
                row.artist,
                row.album,
                row.track,
                row.album_id,
            ),
        )


def _rows(path: Path) -> list[object]:
    with path.open(encoding="utf-8") as stream:
        payload: object = json.load(stream)
    if not isinstance(payload, dict) or not isinstance(payload.get("scrobbles"), list):
        raise ValueError("Last.fm history must contain a scrobbles list.")
    return cast(list[object], payload["scrobbles"])


def build_listening_index(
    source: Path, destination: Path, metadata: ArtifactMetadata
) -> ListeningMetadata:
    """Build a complete unpublished generation, preserving every valid row.

    Args:
        source: Independent checksum-verified source snapshot.
        destination: New temporary SQLite path, never a ready generation.
        metadata: Verified publication identity.

    Returns:
        Metadata persisted inside the completed index.

    Raises:
        ValueError: Any row has invalid metadata or a timestamp.
        OSError: Source files cannot be read.
        sqlite3.Error: Building the derived index fails.
    """
    started = time.monotonic()
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(SCHEMA)
        writer = _IndexWriter(connection)
        for ordinal, row in enumerate(_rows(source)):
            writer.add(row, ordinal)
        connection.executescript(INDEXES)
        result = _metadata(connection, metadata, time.monotonic() - started)
        connection.execute(
            "INSERT INTO metadata VALUES (?)", (json.dumps(asdict(result)),)
        )
        connection.commit()
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("The completed listening index failed validation.")
        return result
    finally:
        connection.close()


def _metadata(
    connection: sqlite3.Connection, source: ArtifactMetadata, duration: float
) -> ListeningMetadata:
    count, first, last, missing = connection.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts), SUM(album_id IS NULL) FROM plays"
    ).fetchone()
    return ListeningMetadata(
        f"{INDEX_VERSION}-{source.sha256}",
        source.sha256,
        source.updated_at,
        datetime.now(UTC).isoformat(),
        first,
        last,
        count,
        missing or 0,
        source.size_bytes,
        round(duration, 3),
    )
