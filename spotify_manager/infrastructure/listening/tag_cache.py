"""Private persistent derived tag cache with complete immutable generations."""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import cast
from urllib.parse import quote

from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.application.listening_tag_ports import TagCacheError
from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_tag_values import CommunityTag
from spotify_manager.domain.listening_tag_values import TagCatalog
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


MAX_CACHED_ARTISTS = 20000
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS observations (artist_key TEXT PRIMARY KEY, "
    "document TEXT NOT NULL, fetched_at TEXT NOT NULL)"
)


def _text(raw: dict[str, object], key: str, *, empty: bool = False) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError("Cached tag field is invalid.")
    return value


def _cached_tags(raw: object) -> tuple[CommunityTag, ...]:
    if not isinstance(raw, list) or len(raw) > 10:
        raise ValueError("Cached tag list is invalid.")
    result = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Cached tag row is invalid.")
        name = _text(row, "name")
        key = listening_identity((name,))
        if key != row.get("key") or key in seen or len(name) > 200:
            raise ValueError("Cached tag identity is invalid.")
        result.append(CommunityTag(key, name))
        seen.add(key)
    return tuple(result)


def decode_tag_metadata(document: str) -> ArtistTagMetadata:
    """Validate persisted derived observations before exposing cached evidence.

    Args:
        document: One credential-free serialized metadata observation.

    Returns:
        Complete validated observation with a fixed public source URL.

    Raises:
        ValueError: The cache row is malformed or its identities disagree.
    """
    value: object = json.loads(document)
    if not isinstance(value, dict):
        raise ValueError("Cached tag observation is invalid.")
    raw = cast(dict[str, object], value)
    name = _text(raw, "artist_name")
    key = _text(raw, "artist_key")
    state = raw.get("state")
    if key != listening_identity((name,)) or state not in (
        "tagged",
        "empty",
        "unresolved",
    ):
        raise ValueError("Cached artist identity or outcome is invalid.")
    tags = _cached_tags(raw.get("tags"))
    if bool(tags) != (state == "tagged"):
        raise ValueError("Cached tag availability is inconsistent.")
    fetched_at = _text(raw, "fetched_at")
    if datetime.fromisoformat(fetched_at).utcoffset() is None:
        raise ValueError("Cached retrieval date needs a timezone.")
    resolved = _text(raw, "resolved_name", empty=True)
    if state != "unresolved" and listening_identity((resolved,)) != key:
        raise ValueError("Cached provider identity is not corroborated.")
    url = "https://www.last.fm/music/" + quote(name, safe="") + "/+tags"
    return ArtistTagMetadata(key, name, resolved, state, tags, fetched_at, url)


class ArtistTagCache:
    """Keep derived observations on disk and only two complete in-memory versions.

    Args:
        root: App-owned cache directory, separate from canonical files and state.
    """

    def __init__(self, root: Path) -> None:
        """Open only the fixed cache filename and recover visibly from corruption.

        Args:
            root: Explicit app-owned cache root selected at bootstrap.
        """
        self._path = root / "artist-tags-v1.sqlite"
        self._lock = RLock()
        self._generations: dict[str, TagCatalog] = {}
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._initialize()
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError:
            self._publish(
                (),
                "Tag cache unavailable; listening history remains available.",
            )

    def _initialize(self) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(SCHEMA)
        self._path.chmod(0o600)

    def _load(self) -> tuple[ArtistTagMetadata, ...]:
        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute(
                "SELECT document FROM observations ORDER BY artist_key LIMIT ?",
                (MAX_CACHED_ARTISTS,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(decode_tag_metadata(row[0]))
        return tuple(result)

    def _publish(
        self, entries: tuple[ArtistTagMetadata, ...], message: str = ""
    ) -> None:
        documents = [asdict(item) for item in entries]
        content = json.dumps(documents, sort_keys=True, ensure_ascii=False)
        token = "t1-" + hashlib.sha256(content.encode()).hexdigest()
        catalog = TagCatalog(token, entries, message)
        with self._lock:
            self._generations.pop(token, None)
            self._generations[token] = catalog
            while len(self._generations) > 2:
                self._generations.pop(next(iter(self._generations)))

    def current(self) -> TagCatalog:
        """Return the most recent complete metadata generation without disk I/O.

        Returns:
            Immutable cache contents, possibly empty with an availability message.
        """
        with self._lock:
            return next(reversed(self._generations.values()))

    def acquire(self, snapshot: str) -> TagCatalog:
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
                    "Tag metadata version expired. Reload this view."
                )
            return catalog

    def write(self, metadata: ArtistTagMetadata) -> None:
        """Commit one validated observation before publishing complete cache data.

        Args:
            metadata: Completed provider outcome with credential-free provenance.

        Raises:
            TagCacheError: Persistence or validation failed; prior data remains.
        """
        try:
            document = json.dumps(asdict(metadata), ensure_ascii=False)
            decode_tag_metadata(document)
            self._commit(metadata, document)
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError:
            raise TagCacheError("Derived tag metadata could not be cached.") from None

    def _commit(self, metadata: ArtistTagMetadata, document: str) -> None:
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

    async def save(self, metadata: ArtistTagMetadata) -> None:
        """Await the fixed SQLite resource operation under drained worker ownership.

        Args:
            metadata: Complete provider observation to persist atomically.

        Raises:
            TagCacheError: The concrete persistence boundary failed.
        """
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.write, metadata))
            await finish_blocking(worker)
