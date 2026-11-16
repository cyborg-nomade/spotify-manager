"""Own lazy published-history refresh, atomic generations, and active readers."""

import asyncio
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Literal

from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningStatus
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.core.library_data.models import LibraryDataError
from spotify_manager.core.library_data.models import artifact_metadata
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.build import INDEX_VERSION
from spotify_manager.infrastructure.listening.build import build_listening_index
from spotify_manager.infrastructure.listening.reader import ListeningIndex
from spotify_manager.infrastructure.scrobble_downloads import ScrobbleHistoryFiles
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


_logger = logging.getLogger(__name__)


class ListeningRuntime:
    """Own a process-isolated disposable index and one source refresh task.

    Args:
        service: Existing durable publication service, used only for reads.
        directory: Runtime-owned temporary cache released on shutdown.
    """

    def __init__(
        self, service: LibraryDataService, directory: TemporaryDirectory[str]
    ) -> None:
        """Own one source resource, isolated cache, and lazily started refresh task."""
        self._service = service
        self._directory = directory
        self._root = Path(directory.name)
        self._lock = RLock()
        self._task: asyncio.Task[None] | None = None
        self._checked_at = float("-inf")
        self._generations: dict[str, ListeningIndex] = {}
        self._readers: dict[str, int] = {}
        self._current: ListeningIndex | None = None
        self._error = ""
        self._missing = False
        self._closed = False

    def status(self, *, refresh: bool = False) -> ListeningStatus:
        """Schedule a bounded manifest check and return current index readiness.

        Args:
            refresh: Check now without duplicating an already-running worker.

        Returns:
            Last complete generation metadata and visible build/failure status.
        """
        if not self._closed and self._due(refresh):
            self._checked_at = time.monotonic()
            self._task = asyncio.create_task(self._refresh(), name="listening-index")
        with self._lock:
            checking = self._task is not None and not self._task.done()
            return self._status(checking)

    def _due(self, refresh: bool) -> bool:
        running = self._task is not None and not self._task.done()
        return not running and (refresh or time.monotonic() - self._checked_at >= 60)

    def _status(self, checking: bool) -> ListeningStatus:
        metadata = self._current.metadata if self._current is not None else None
        if metadata is not None:
            state: Literal["stale", "ready"] = (
                "stale" if self._error or self._missing else "ready"
            )
            message = self._error or (
                "Published history is missing; showing the last complete index."
                if self._missing
                else "Recorded listening history is ready."
            )
            return ListeningStatus(state, metadata, message, checking)
        if self._error:
            return ListeningStatus("error", None, self._error, checking)
        if self._missing:
            return ListeningStatus(
                "missing",
                None,
                "Sync Last.fm history from the Data Signal Board first.",
                checking,
            )
        return ListeningStatus(
            "building", None, "Preparing recorded listening history…", checking
        )

    async def _refresh(self) -> None:
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.refresh_source))
            await finish_blocking(worker)

    def refresh_source(self) -> None:
        """Read the source manifest and atomically replace only a complete index.

        A concrete blocking resource operation invoked through asyncio.to_thread.
        It never publishes source data or executes another application stage.
        """
        try:
            self._update()
        except LibraryDataError, OSError, ValueError, TypeError, sqlite3.Error:
            _logger.warning(
                "Listening index refresh failed; retaining the complete generation.",
                exc_info=True,
            )
            with self._lock:
                self._error = (
                    "Stored history could not be indexed. "
                    "Retry shortly or check the Last.fm publication."
                )

    def _update(self) -> None:
        manifest = self._service.snapshot()
        metadata = artifact_metadata(manifest.document, "scrobbles")
        with self._lock:
            self._missing = metadata is None
            self._error = ""
        if metadata is None:
            return
        token = f"{INDEX_VERSION}-{metadata.sha256}"
        with self._lock:
            unchanged = (
                self._current is not None
                and self._current.metadata.snapshot == token
                and self._current.path.exists()
            )
        if unchanged:
            return
        self._build()

    def _build(self) -> None:
        snapshot = ScrobbleHistoryFiles(self._service, self._root).prepare()
        if snapshot is None:
            with self._lock:
                self._missing = True
            return
        temporary = self._root / "history.building"
        try:
            metadata = build_listening_index(
                snapshot.path, temporary, snapshot.metadata
            )
            destination = self._root / f"{metadata.snapshot}.sqlite"
            temporary.replace(destination)
            self._publish(ListeningIndex(destination, metadata))
        finally:
            snapshot.close()
            temporary.unlink(missing_ok=True)

    def _publish(self, index: ListeningIndex) -> None:
        with self._lock:
            self._generations[index.metadata.snapshot] = index
            self._current = index
            self._error = ""
            self._missing = False
            self._prune()

    @contextmanager
    def acquire(self, snapshot: str) -> Iterator[ListeningIndex]:
        """Pin a ready generation until an HTTP operation finishes.

        Args:
            snapshot: Version token obtained from the status endpoint.

        Yields:
            One complete immutable history reader.

        Raises:
            ListeningNotReadyError: No completed index exists.
            ListeningVersionError: The token has expired.
        """
        with self._lock:
            index = self._generation(snapshot)
            self._readers[snapshot] = self._readers.get(snapshot, 0) + 1
        try:
            yield index
        finally:
            with self._lock:
                self._readers[snapshot] -= 1
                self._prune()

    def _generation(self, snapshot: str) -> ListeningIndex:
        if self._current is None:
            raise ListeningNotReadyError("Listening history is still being prepared.")
        index = self._generations.get(snapshot)
        if index is None:
            raise ListeningVersionError(
                "History version expired. Reload the selection."
            )
        return index

    def _prune(self) -> None:
        candidates = tuple(self._generations)[:-2]
        for token in candidates:
            if self._readers.get(token, 0):
                continue
            index = self._generations.pop(token)
            for path in self._root.glob(index.path.stem + ".*"):
                path.unlink(missing_ok=True)
            self._readers.pop(token, None)

    async def close(self) -> None:
        """Finish the owned worker before deleting disposable runtime storage."""
        self._closed = True
        try:
            if self._task is not None:
                await finish_blocking(self._task)
        finally:
            self._directory.cleanup()
