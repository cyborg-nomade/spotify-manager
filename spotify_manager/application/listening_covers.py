"""Named cached-cover analysis and explicit bounded MusicBrainz enrichment."""

import asyncio

from spotify_manager.application.listening_cover_ports import CoverCache
from spotify_manager.application.listening_cover_ports import CoverCacheError
from spotify_manager.application.listening_cover_ports import CoverFetchRequest
from spotify_manager.application.listening_cover_ports import CoverFetchState
from spotify_manager.application.listening_cover_ports import CoverFetchStatus
from spotify_manager.application.listening_cover_ports import CoverSource
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_cover_values import CoverArtwork
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_cover_values import ListeningQuilt
from spotify_manager.domain.listening_cover_values import QuiltOptions
from spotify_manager.domain.listening_quilt import get_quilt_analysis
from spotify_manager.domain.listening_values import ListeningQuery


REQUEST_INTERVAL = 1.1


def get_listening_covers(
    index: ListeningReads,
    catalog: CoverCatalog,
    query: ListeningQuery,
    options: QuiltOptions,
) -> ListeningQuilt:
    """Read only complete cached cover metadata for a pinned history selection.

    Args:
        index: Pinned complete history resource.
        catalog: Independently pinned current cover evidence.
        query: Applied dates, timezone and artist/rhythm filters.
        options: Applied bounded quilt size and title/artist search.

    Returns:
        Ranked album quilt, complete scope counts and current cover evidence.
    """
    return get_quilt_analysis(
        index.lifetimes(query, "album"), index.counts(query), catalog, options
    )


class ListeningCoverEnrichment:
    """Own one explicit lookup batch with direct named provider/cache calls.

    Args:
        cache: Complete, persistent derived metadata generations.
        source: Configured public album-cover read resource.
    """

    def __init__(self, cache: CoverCache, source: CoverSource) -> None:
        """Bind the concrete resources and initialize an idle batch.

        Args:
            cache: Derived metadata resource, separate from canonical data.
            source: Public read provider; no account or playlist mutation API.
        """
        self.cache = cache
        self.source = source
        self._task: asyncio.Task[None] | None = None
        self._state: CoverFetchState = "idle"
        self._total = 0
        self._completed = 0
        self._message = "Fetch a bounded batch to expand available cover coverage."
        self._history: str | None = None
        self._closed = False

    def status(self) -> CoverFetchStatus:
        """Present lookup progress while preserving complete cached observations.

        Returns:
            Current lifecycle, cached version and safe progress explanation.
        """
        catalog = self.cache.current()
        if self._state == "cancelling" and self._task is not None and self._task.done():
            self._state = "cancelled"
            self._message = "Lookup cancelled; completed metadata is retained."
        message = self._message
        if not self.source.configured:
            message = (
                "MusicBrainz lookup is not configured; cached views remain available."
            )
        if catalog.message:
            message += " " + catalog.message
        return CoverFetchStatus(
            self._state,
            self.source.configured,
            self._total,
            self._completed,
            message,
            catalog.snapshot,
            len(catalog.entries),
            self._history,
            not bool(catalog.message),
        )

    def start(self, request: CoverFetchRequest) -> CoverFetchStatus:
        """Start one bounded batch after the HTTP boundary selects its albums.

        Args:
            request: Album/artist names captured from a pinned listening selection.

        Returns:
            Accepted progress or the already-running batch without duplication.

        Raises:
            CoverSourceError: Configuration is missing or the resource is closed.
            ValueError: The batch exceeds the fixed ten-album bound.
        """
        if self._closed or not self.source.configured:
            raise CoverSourceError("Public MusicBrainz cover lookup is not configured.")
        if self._task is not None and not self._task.done():
            return self.status()
        if len(request.albums) > 10:
            raise ValueError("Choose at most ten albums per lookup batch.")
        self._total = len(request.albums)
        self._completed = 0
        self._history = request.history_snapshot
        self._state = "running"
        self._message = (
            "Fetching public cover metadata; existing history stays available."
        )
        self._task = asyncio.create_task(self._run(request), name="listening-covers")
        return self.status()

    async def _run(self, request: CoverFetchRequest) -> None:
        try:
            await self._fetch(request)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._message = (
                "Lookup cancelled; completed cached observations are retained."
            )
            raise
        except CoverSourceError, CoverCacheError:
            self._state = "error"
            self._message = (
                "Cover lookup unavailable; completed metadata is retained. Retry later."
            )
        else:
            self._state = "complete"
            self._message = (
                "Lookup complete. Cached evidence describes current "
                "representative artwork."
            )

    async def _fetch(self, request: CoverFetchRequest) -> None:
        for album in request.albums:
            if self._completed:
                await asyncio.sleep(REQUEST_INTERVAL)
            metadata = await self.source.fetch(album)
            await self._save(metadata)

    async def _save(self, metadata: CoverFetchResult) -> None:
        try:
            await self.cache.save(metadata)
        finally:
            if metadata.metadata in self.cache.current().entries:
                self._completed += 1

    def cancel(self) -> CoverFetchStatus:
        """Request cancellation while the concrete resource drains active work.

        Returns:
            Cancellation progress without discarding completed cached entries.
        """
        if self._task is not None and not self._task.done():
            self._state = "cancelling"
            self._message = "Finishing the active lookup before stopping."
            self._task.cancel()
        return self.status()

    async def close(self) -> None:
        """Cancel and drain the owned lookup task before application shutdown."""
        self._closed = True
        self.cancel()
        if self._task is None:
            return
        try:
            await self._task
        except asyncio.CancelledError:
            return


def get_quilt_image(catalog: CoverCatalog, album_key: str) -> bytes | None:
    """Find only bytes supported by one album in the pinned complete generation.

    Args:
        catalog: Independently pinned cover metadata and immutable image bytes.
        album_key: Requested original history identity.

    Returns:
        Validated JPEG bytes, or no image when this album has no supporting art.
    """
    for item in catalog.entries:
        if item.album_key == album_key:
            return _image_bytes(catalog, item.artwork)
    return None


def _image_bytes(catalog: CoverCatalog, artwork: CoverArtwork | None) -> bytes | None:
    if artwork is None:
        return None
    for image in catalog.images:
        if image.sha256 == artwork.sha256:
            return image.content
    return None
