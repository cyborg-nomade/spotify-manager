"""Persistent, bounded country evidence with independent immutable versions."""

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import cast
from uuid import UUID

from spotify_manager.application.listening_origin_ports import OriginCacheError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import OriginCandidate
from spotify_manager.domain.listening_origin_values import OriginCatalog
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


MAX_CACHED_ARTISTS = 20000
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS observations (artist_key TEXT PRIMARY KEY, "
    "document TEXT NOT NULL, fetched_at TEXT NOT NULL)"
)


def _text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError("Cached country field is invalid.")
    return value


def _candidate(raw: object) -> OriginCandidate:
    if not isinstance(raw, dict):
        raise ValueError("Cached country candidate is invalid.")
    mbid = _text(raw, "mbid")
    if str(UUID(mbid)) != mbid:
        raise ValueError("Cached provider identity is invalid.")
    countries = raw.get("countries")
    if not isinstance(countries, list) or len(countries) > 10:
        raise ValueError("Cached country codes are invalid.")
    codes = []
    for code in countries:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}", code):
            raise ValueError("Cached country code is invalid.")
        codes.append(code)
    if codes != sorted(set(codes)):
        raise ValueError("Cached country codes must be unique and ordered.")
    return OriginCandidate(
        mbid,
        _text(raw, "name"),
        _text(raw, "description"),
        _text(raw, "artist_type"),
        _text(raw, "area"),
        _text(raw, "begin_area"),
        tuple(codes),
    )


def _candidates(raw: object) -> tuple[OriginCandidate, ...]:
    if not isinstance(raw, list) or len(raw) > 5:
        raise ValueError("Cached candidate list is invalid.")
    candidates = tuple(_candidate(item) for item in raw)
    if len({item.mbid for item in candidates}) != len(candidates):
        raise ValueError("Cached candidates are not distinct.")
    return candidates


def _coherent(state: str, count: int, candidates: tuple[OriginCandidate, ...]) -> bool:
    if len(candidates) != min(count, 5):
        return False
    if state == "matched":
        return count == 1
    if state == "unmatched":
        return count == 0
    if state == "ambiguous":
        return count > 1
    return state == "incomplete"


def decode_origin_metadata(document: str) -> ArtistOriginMetadata:
    """Validate complete persisted evidence before publishing any cache version.

    Args:
        document: Credential-free serialized provider observation.

    Returns:
        Complete bounded identity-checked metadata.

    Raises:
        ValueError: Fields, identities, outcomes or retrieval times disagree.
    """
    value: object = json.loads(document)
    if not isinstance(value, dict):
        raise ValueError("Cached country observation is invalid.")
    raw = cast(dict[str, object], value)
    name, key = _text(raw, "artist_name"), _text(raw, "artist_key")
    state, count = raw.get("state"), raw.get("candidate_count")
    if not name.strip() or listening_identity((name,)) != key:
        raise ValueError("Cached history identity is invalid.")
    candidates = _candidates(raw.get("candidates"))
    if state not in ("matched", "unmatched", "ambiguous", "incomplete"):
        raise ValueError("Cached country outcome is invalid.")
    if (
        type(count) is not int
        or not 0 <= count <= 100
        or not _coherent(state, count, candidates)
    ):
        raise ValueError("Cached country evidence is inconsistent.")
    if any(listening_identity((item.name,)) != key for item in candidates):
        raise ValueError("Cached provider names are not corroborated.")
    fetched_at = _text(raw, "fetched_at")
    if datetime.fromisoformat(fetched_at).utcoffset() is None:
        raise ValueError("Cached retrieval date needs a timezone.")
    return ArtistOriginMetadata(key, name, state, candidates, count, fetched_at)


class ArtistOriginCache:
    """Keep derived observations on disk and only two complete in-memory versions.

    Args:
        root: App-owned cache directory, separate from canonical files and state.
    """

    def __init__(self, root: Path) -> None:
        """Open only the fixed cache filename and recover visibly from corruption.

        Args:
            root: Explicit app-owned cache root selected at bootstrap.
        """
        self._path = root / "artist-origins-v1.sqlite"
        self._lock = RLock()
        self._generations: dict[str, OriginCatalog] = {}
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._initialize()
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError:
            self._publish(
                (),
                "Country cache unavailable; listening history remains available.",
            )

    def _initialize(self) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(SCHEMA)
        self._path.chmod(0o600)

    def _load(self) -> tuple[ArtistOriginMetadata, ...]:
        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute(
                "SELECT document FROM observations ORDER BY artist_key LIMIT ?",
                (MAX_CACHED_ARTISTS,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(decode_origin_metadata(row[0]))
        return tuple(result)

    def _publish(
        self, entries: tuple[ArtistOriginMetadata, ...], message: str = ""
    ) -> None:
        documents = [asdict(item) for item in entries]
        content = json.dumps(documents, sort_keys=True, ensure_ascii=False)
        token = "o1-" + hashlib.sha256(content.encode()).hexdigest()
        catalog = OriginCatalog(token, entries, message)
        with self._lock:
            self._generations.pop(token, None)
            self._generations[token] = catalog
            while len(self._generations) > 2:
                self._generations.pop(next(iter(self._generations)))

    def current(self) -> OriginCatalog:
        """Return the most recent complete metadata generation without disk I/O.

        Returns:
            Immutable cache contents, possibly empty with an availability message.
        """
        with self._lock:
            return next(reversed(self._generations.values()))

    def acquire(self, snapshot: str) -> OriginCatalog:
        """Pin an available generation independently of later cache writes.

        Args:
            snapshot: Explicit metadata content identity.

        Returns:
            Complete immutable metadata retained by the caller.

        Raises:
            ListeningVersionError: The requested metadata generation expired.
        """
        with self._lock:
            catalog = self._generations.get(snapshot)
            if catalog is None:
                raise ListeningVersionError(
                    "Country metadata version expired. Reload this view."
                )
            return catalog

    def write(self, metadata: ArtistOriginMetadata) -> None:
        """Commit one validated observation before publishing complete cache data.

        Args:
            metadata: Completed provider outcome with credential-free provenance.

        Raises:
            OriginCacheError: Persistence or validation failed; prior data remains.
        """
        try:
            document = json.dumps(asdict(metadata), ensure_ascii=False)
            decode_origin_metadata(document)
            self._commit(metadata, document)
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError:
            raise OriginCacheError(
                "Derived country metadata could not be cached."
            ) from None

    def _commit(self, metadata: ArtistOriginMetadata, document: str) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "INSERT INTO observations VALUES (?, ?, ?) ON CONFLICT(artist_key) "
                "DO UPDATE SET document=excluded.document, "
                "fetched_at=excluded.fetched_at",
                (metadata.artist_key, document, metadata.fetched_at),
            )
            connection.execute(
                "DELETE FROM observations WHERE artist_key IN (SELECT artist_key "
                "FROM observations ORDER BY fetched_at, artist_key "
                "LIMIT MAX(0, (SELECT COUNT(*) FROM observations) - ?))",
                (MAX_CACHED_ARTISTS,),
            )

    async def save(self, metadata: ArtistOriginMetadata) -> None:
        """Await the fixed SQLite resource operation under drained worker ownership.

        Args:
            metadata: Complete provider observation to persist atomically.

        Raises:
            OriginCacheError: The concrete persistence boundary failed.
        """
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.write, metadata))
            await finish_blocking(worker)

    def _install(self, entries: tuple[ArtistOriginMetadata, ...]) -> None:
        try:
            rows = []
            for entry in entries:
                document = json.dumps(asdict(entry), ensure_ascii=False)
                decode_origin_metadata(document)
                rows.append((entry.artist_key, document, entry.fetched_at))
            with closing(sqlite3.connect(self._path)) as connection, connection:
                connection.execute("DELETE FROM observations")
                connection.executemany(
                    "INSERT INTO observations VALUES (?, ?, ?)", rows
                )
            self._publish(entries)
        except OSError, sqlite3.Error, ValueError, TypeError:
            raise OriginCacheError(
                "Durable country evidence could not be installed locally."
            ) from None

    async def install(self, entries: tuple[ArtistOriginMetadata, ...]) -> None:
        """Publish a complete immutable cache generation from a durable checkpoint.

        Args:
            entries: All committed validated country observations.
        """
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self._install, entries))
            await finish_blocking(worker)
