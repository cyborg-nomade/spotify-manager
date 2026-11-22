"""Bounded SQLite cover observations with atomic images and immutable generations."""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from spotify_manager.application.listening_cover_ports import CoverCacheError
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_cover_values import CoverImage
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.cover_codec import MAX_DOCUMENT_BYTES
from spotify_manager.infrastructure.listening.cover_codec import decode_cover_image
from spotify_manager.infrastructure.listening.cover_codec import decode_cover_metadata
from spotify_manager.infrastructure.listening.cover_http import MAX_IMAGE_BYTES
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


MAX_CACHED_ALBUMS = 256
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS observations (album_key TEXT PRIMARY KEY, "
    "document TEXT NOT NULL, fetched_at TEXT NOT NULL, image BLOB)"
)


def _decode(document: str, content: bytes | None) -> CoverFetchResult:
    metadata = decode_cover_metadata(document)
    return CoverFetchResult(metadata, decode_cover_image(metadata, content))


class AlbumCoverCache:
    """Retain bounded derived artwork separately from canonical history and state.

    Args:
        root: Explicit app-owned cache directory, separate for each process.
    """

    def __init__(self, root: Path) -> None:
        """Open only the fixed derived filename and expose corrupt storage visibly.

        Args:
            root: App-owned derived cache location.
        """
        self._path = root / "album-covers-v1.sqlite"
        self._lock = RLock()
        self._generations: dict[str, CoverCatalog] = {}
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._initialize()
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError, CoverSourceError:
            self._publish(
                (), "Cover cache unavailable; listening history remains available."
            )

    def _initialize(self) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute("PRAGMA auto_vacuum=FULL")
            connection.execute("PRAGMA max_page_count=20000")
            connection.execute(SCHEMA)
        self._path.chmod(0o600)

    def _load(self) -> tuple[CoverFetchResult, ...]:
        sql = (
            "SELECT substr(document,1,?), CASE WHEN length(image)<=? "
            "THEN image ELSE NULL END FROM observations ORDER BY album_key LIMIT ?"
        )
        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute(
                sql, (MAX_DOCUMENT_BYTES + 1, MAX_IMAGE_BYTES, MAX_CACHED_ALBUMS + 1)
            ).fetchall()
        if len(rows) > MAX_CACHED_ALBUMS:
            raise ValueError("Cached album count exceeded its limit.")
        return tuple(_decode(document, content) for document, content in rows)

    def _publish(
        self, results: tuple[CoverFetchResult, ...], message: str = ""
    ) -> None:
        entries = tuple(item.metadata for item in results)
        documents = [asdict(item) for item in entries]
        content = json.dumps(documents, sort_keys=True, ensure_ascii=False)
        token = "c1-" + hashlib.sha256(content.encode()).hexdigest()
        images: dict[str, CoverImage] = {}
        for item in results:
            if item.image is not None:
                images[item.image.sha256] = item.image
        catalog = CoverCatalog(token, entries, tuple(images.values()), message)
        with self._lock:
            self._generations.pop(token, None)
            self._generations[token] = catalog
            while len(self._generations) > 2:
                self._generations.pop(next(iter(self._generations)))

    def current(self) -> CoverCatalog:
        """Return the latest complete metadata and image generation without I/O.

        Returns:
            Immutable complete catalog, possibly empty with a cache error message.
        """
        with self._lock:
            return next(reversed(self._generations.values()))

    def acquire(self, snapshot: str) -> CoverCatalog:
        """Pin metadata and its bytes together while later cache writes complete.

        Args:
            snapshot: Explicit independent cover generation.

        Returns:
            Complete immutable catalog retained by the caller.

        Raises:
            ListeningVersionError: The cover generation expired.
        """
        with self._lock:
            catalog = self._generations.get(snapshot)
            if catalog is None:
                raise ListeningVersionError("Cover version expired. Reload this view.")
            return catalog

    def write(self, result: CoverFetchResult) -> None:
        """Commit one validated observation and image before publishing any version.

        Args:
            result: Complete provider outcome and optional validated artwork.

        Raises:
            CoverCacheError: Validation or persistence failed; prior versions remain.
        """
        try:
            document = json.dumps(asdict(result.metadata), ensure_ascii=False)
            content = result.image.content if result.image else None
            decoded = _decode(document, content)
            if decoded != result:
                raise ValueError("Cover image identity disagrees.")
            self._commit(result, document)
            self._publish(self._load())
        except OSError, sqlite3.Error, ValueError, TypeError, CoverSourceError:
            raise CoverCacheError(
                "Derived cover metadata could not be cached."
            ) from None

    def _commit(self, result: CoverFetchResult, document: str) -> None:
        metadata = result.metadata
        content = result.image.content if result.image else None
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute("PRAGMA max_page_count=20000")
            connection.execute(
                "INSERT INTO observations VALUES (?, ?, ?, ?) ON CONFLICT(album_key) "
                "DO UPDATE SET document=excluded.document, "
                "fetched_at=excluded.fetched_at, image=excluded.image",
                (metadata.album_key, document, metadata.fetched_at, content),
            )
            connection.execute(
                "DELETE FROM observations WHERE album_key IN (SELECT album_key "
                "FROM observations ORDER BY fetched_at, album_key "
                "LIMIT MAX(0, (SELECT COUNT(*) FROM observations) - ?))",
                (MAX_CACHED_ALBUMS,),
            )

    async def save(self, metadata: CoverFetchResult) -> None:
        """Drain the atomic SQLite operation while retaining bounded worker capacity.

        Args:
            metadata: Completed observation and its optional immutable image.

        Raises:
            CoverCacheError: Persistence or validation failed.
        """
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.write, metadata))
            await finish_blocking(worker)
