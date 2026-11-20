"""Own bounded immutable collection generations independently of history."""

import asyncio
import time
from dataclasses import dataclass
from threading import RLock
from typing import Literal

from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.core.library_data.models import LibraryDataError
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import MirrorSource
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.library_source import LibraryPublications
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class LibraryStatus:
    """Expose publication readiness without clearing available history.

    Args:
        state: Initial build/error or usable current/stale evidence.
        snapshot: Pinned collection generation when available.
        sources: Coverage of all three collection publications.
        message: Data-free recovery explanation.
        checking: Whether a background revision check is running.
    """

    state: Literal["ready", "building", "stale", "error"]
    snapshot: str | None
    sources: tuple[MirrorSource, ...]
    message: str
    checking: bool


class LibraryRuntime:
    """Keep source reads in an owned worker and retain two complete generations.

    Args:
        service: Existing read-only durable publication access.
    """

    def __init__(self, service: LibraryDataService) -> None:
        """Own one concrete read resource, lock, worker and bounded generations."""
        self._source = LibraryPublications(service)
        self._lock = RLock()
        self._generations: dict[str, LibraryCatalog] = {}
        self._task: asyncio.Task[None] | None = None
        self._checked_at = float("-inf")
        self._error = False
        self._closed = False

    def status(self, *, refresh: bool = False) -> LibraryStatus:
        """Schedule at most one source check while serving complete generations.

        Args:
            refresh: Check now instead of waiting for the sixty-second interval.

        Returns:
            Current publication coverage and worker state.
        """
        running = self._task is not None and not self._task.done()
        due = refresh or time.monotonic() - self._checked_at >= 60
        if not self._closed and not running and due:
            self._checked_at = time.monotonic()
            self._task = asyncio.create_task(self._refresh(), name="listening-library")
            running = True
        with self._lock:
            return self._status(running)

    def _status(self, running: bool) -> LibraryStatus:
        if not self._generations:
            initial: Literal["error", "building"] = (
                "error" if self._error else "building"
            )
            return LibraryStatus(
                initial,
                None,
                (),
                "Collection publications unavailable."
                if self._error
                else "Preparing collection evidence…",
                running,
            )
        catalog = next(reversed(self._generations.values()))
        state: Literal["stale", "ready"] = "stale" if self._error else "ready"
        message = (
            "Latest check failed; showing the last complete collection publications."
            if self._error
            else "Collection publication evidence is ready."
        )
        return LibraryStatus(state, catalog.snapshot, catalog.sources, message, running)

    async def _refresh(self) -> None:
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.refresh_source))
            await finish_blocking(worker)

    def refresh_source(self) -> None:
        """Read concrete published artifacts through the standard thread bridge.

        This bound resource method is required by asyncio.to_thread; it does not
        execute an application stage or publish canonical data.
        """
        try:
            catalog = self._source.read()
        except LibraryDataError, OSError, ValueError, TypeError:
            with self._lock:
                self._error = True
            return
        with self._lock:
            self._error = False
            retained = self._generations.pop(catalog.snapshot, catalog)
            self._generations[catalog.snapshot] = retained
            while len(self._generations) > 2:
                self._generations.pop(next(iter(self._generations)))

    def acquire(self, snapshot: str) -> LibraryCatalog:
        """Retain one immutable in-memory generation for the calling request.

        Args:
            snapshot: Collection version returned by its status route.

        Returns:
            Complete generation, retained by the caller even after eviction.

        Raises:
            ListeningNotReadyError: No complete publication is available yet.
            ListeningVersionError: The requested generation has expired.
        """
        with self._lock:
            if not self._generations:
                raise ListeningNotReadyError(
                    "Collection evidence is still being prepared."
                )
            catalog = self._generations.get(snapshot)
            if catalog is None:
                raise ListeningVersionError(
                    "Collection version expired. Reload this comparison."
                )
            return catalog

    async def close(self) -> None:
        """Drain the owned worker before releasing process-local generations."""
        self._closed = True
        try:
            if self._task is not None:
                await finish_blocking(self._task)
        finally:
            with self._lock:
                self._generations.clear()
