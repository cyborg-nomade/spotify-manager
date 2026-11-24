"""Named cached-cover analysis and explicit bounded MusicBrainz enrichment."""

import asyncio
from time import monotonic

from spotify_manager.application.listening_cover_ports import CoverCache
from spotify_manager.application.listening_cover_ports import CoverCacheError
from spotify_manager.application.listening_cover_ports import CoverFetchRequest
from spotify_manager.application.listening_cover_ports import CoverFetchState
from spotify_manager.application.listening_cover_ports import CoverFetchStatus
from spotify_manager.application.listening_cover_ports import CoverSource
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_cover_ports import QuickCoverSource
from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_cover_values import CoverArtwork
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_cover_values import LastFmArtwork
from spotify_manager.domain.listening_cover_values import ListeningQuilt
from spotify_manager.domain.listening_cover_values import QuiltOptions
from spotify_manager.domain.listening_quilt import get_quilt_analysis
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankedEntity


REQUEST_INTERVAL = 1.1
LASTFM_RECHECK_SECONDS = 15 * 60
LASTFM_RECENT_LIMIT = 256
LASTFM_QUILT_LIMIT = 49


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

    def __init__(
        self,
        cache: CoverCache,
        source: CoverSource,
        quick_source: QuickCoverSource | None = None,
    ) -> None:
        """Bind the concrete resources and initialize an idle batch.

        Args:
            cache: Derived metadata resource, separate from canonical data.
            source: Public read provider; no account or playlist mutation API.
            quick_source: Optional first pass before the archive lookup.
        """
        self.cache = cache
        self.source = source
        self.quick_source = quick_source
        self._lastfm_attempts: dict[str, float] = {}
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
        return self._start(request, lastfm_only=False)

    def start_lastfm(self, request: CoverFetchRequest) -> CoverFetchStatus:
        """Queue missing tiles for a Last.fm-only pass on the displayed quilt.

        Args:
            request: Missing artwork candidates from one pinned selection.

        Returns:
            Progress for the owned batch, or the current status when idle.

        Raises:
            ValueError: The request exceeds the maximum visible quilt size.
        """
        if len(request.albums) > LASTFM_QUILT_LIMIT:
            raise ValueError("Choose at most 49 albums for an automatic cover pass.")
        if self._closed or self.quick_source is None or not self.quick_source.available:
            return self.status()
        if self._task is not None and not self._task.done():
            return self.status()
        albums = self._unchecked_albums(request.albums)
        if not albums or self.cache.current().message:
            return self.status()
        return self._start(
            CoverFetchRequest(albums, request.history_snapshot), lastfm_only=True
        )

    def _unchecked_albums(
        self, albums: tuple[RankedEntity, ...]
    ) -> tuple[RankedEntity, ...]:
        existing = set()
        for item in self.cache.current().entries:
            if item.artwork:
                existing.add(item.album_key)
        now = monotonic()
        result = []
        for album in albums:
            if (
                album.key not in existing
                and self._lastfm_attempts.get(album.key, now) <= now
            ):
                result.append(album)
        return tuple(result)

    def _start(
        self, request: CoverFetchRequest, *, lastfm_only: bool
    ) -> CoverFetchStatus:
        self._total = len(request.albums)
        self._completed = 0
        self._history = request.history_snapshot
        self._state = "running"
        self._message = (
            "Checking Last.fm for missing covers."
            if lastfm_only
            else (
                "Fetching public cover metadata. Temporary provider failures "
                "retry automatically and may take a few minutes. "
                "You can cancel while waiting."
            )
        )
        self._task = asyncio.create_task(
            self._run(request, lastfm_only), name="listening-covers"
        )
        return self.status()

    async def _run(self, request: CoverFetchRequest, lastfm_only: bool) -> None:
        try:
            await self._fetch(request, lastfm_only)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._message = (
                "Lookup cancelled; completed cached observations are retained."
            )
            raise
        except CoverSourceError as error:
            self._state = "error"
            self._message = f"{error} Completed cover lookups are saved."
        except CoverCacheError:
            self._state = "error"
            self._message = "Cover metadata could not be saved to the local cache."
        else:
            self._state = "complete"
            if lastfm_only:
                self._message = (
                    "Last.fm check finished. Use Fetch public album covers to search "
                    "for remaining artwork."
                )
            else:
                self._message = (
                    "Lookup complete. Cached evidence describes current "
                    "representative artwork."
                )

    async def _fetch(self, request: CoverFetchRequest, lastfm_only: bool) -> None:
        albums = request.albums
        if self.quick_source is not None:
            if not lastfm_only:
                self._message = "Checking Last.fm for all requested covers first."
            albums = await self._fetch_quickly(albums, self.quick_source)
        if lastfm_only:
            return
        if self.quick_source is not None and albums:
            self._message = (
                "Checking Cover Art Archive for remaining covers. "
                "Temporary failures retry automatically."
            )
        for album in albums:
            if self._completed:
                await asyncio.sleep(REQUEST_INTERVAL)
            metadata = await self.source.fetch(album)
            await self._save(metadata)

    async def _fetch_quickly(
        self, albums: tuple[RankedEntity, ...], source: QuickCoverSource
    ) -> tuple[RankedEntity, ...]:
        missing: list[RankedEntity] = []
        for index, album in enumerate(albums):
            if not source.available:
                return tuple(missing) + albums[index:]
            if index:
                await asyncio.sleep(REQUEST_INTERVAL)
            self._record_lastfm_attempt(album.key)
            result = await source.fetch(album)
            if result is None:
                missing.append(album)
                continue
            await self._save(result)
        return tuple(missing)

    def _record_lastfm_attempt(self, key: str) -> None:
        self._lastfm_attempts.pop(key, None)
        self._lastfm_attempts[key] = monotonic() + LASTFM_RECHECK_SECONDS
        if len(self._lastfm_attempts) > LASTFM_RECENT_LIMIT:
            oldest = next(iter(self._lastfm_attempts))
            del self._lastfm_attempts[oldest]

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
        Validated JPEG or PNG bytes, or no image for this album.
    """
    for item in catalog.entries:
        if item.album_key == album_key:
            return _image_bytes(catalog, item.artwork)
    return None


def _image_bytes(
    catalog: CoverCatalog, artwork: CoverArtwork | LastFmArtwork | None
) -> bytes | None:
    if artwork is None:
        return None
    for image in catalog.images:
        if image.sha256 == artwork.sha256:
            return image.content
    return None
