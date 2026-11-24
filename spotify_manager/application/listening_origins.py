"""Named cached-country analysis and explicit bounded MusicBrainz enrichment."""

import asyncio
from datetime import UTC
from datetime import datetime

from spotify_manager.application.listening_origin_ports import OriginArchive
from spotify_manager.application.listening_origin_ports import OriginCache
from spotify_manager.application.listening_origin_ports import OriginCacheError
from spotify_manager.application.listening_origin_ports import OriginFetchRequest
from spotify_manager.application.listening_origin_ports import OriginFetchState
from spotify_manager.application.listening_origin_ports import OriginFetchStatus
from spotify_manager.application.listening_origin_ports import OriginSource
from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import ListeningOrigins
from spotify_manager.domain.listening_origin_values import OriginCatalog
from spotify_manager.domain.listening_origin_values import OriginOptions
from spotify_manager.domain.listening_origins import get_origin_analysis
from spotify_manager.domain.listening_origins import origin_backfill_candidates
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankedEntity


REQUEST_INTERVAL = 1.1
ORIGIN_CHECKPOINT_SIZE = 50
ORIGIN_BACKFILL_LIMIT = 20000


def get_listening_origins(
    index: ListeningReads,
    catalog: OriginCatalog,
    query: ListeningQuery,
    options: OriginOptions,
) -> ListeningOrigins:
    """Read only complete cached country metadata for a pinned history selection.

    Args:
        index: Pinned complete history resource.
        catalog: Independently pinned current country evidence.
        query: Applied dates, timezone and artist/rhythm filters.
        options: Applied bounded country and evidence filters.

    Returns:
        Complete country counts and a page of original candidate evidence.
    """
    return get_origin_analysis(index.lifetimes(query, "artist"), catalog, options)


def prepare_origin_backfill(
    index: ListeningReads, catalog: OriginCatalog, limit: int
) -> OriginFetchRequest:
    """Capture missing artists across the exact bounds of a published history.

    Args:
        index: Pinned complete history resource.
        catalog: Current complete lookup evidence.
        limit: Maximum number of artists to queue.

    Returns:
        Requested artist identities and their source snapshot.
    """
    metadata = index.metadata
    if metadata.first_ms is None or metadata.last_ms is None:
        return OriginFetchRequest((), metadata.snapshot)
    start = datetime.fromtimestamp(metadata.first_ms / 1000, UTC).date()
    end = datetime.fromtimestamp(metadata.last_ms / 1000, UTC).date()
    artists = index.lifetimes(ListeningQuery(start, end, "UTC"), "artist")
    selected = origin_backfill_candidates(artists, catalog, limit)
    return OriginFetchRequest(selected, metadata.snapshot)


class ListeningOriginEnrichment:
    """Own one explicit lookup batch with direct named provider/cache calls.

    Args:
        cache: Complete, persistent derived metadata generations.
        source: Configured public artist-country read resource.
    """

    def __init__(
        self,
        cache: OriginCache,
        source: OriginSource,
        archive: OriginArchive | None = None,
    ) -> None:
        """Bind the concrete resources and initialize an idle batch.

        Args:
            cache: Derived metadata resource, separate from canonical data.
            source: Public read provider; no account or playlist mutation API.
            archive: Optional durable checkpoint resource for full-history loading.
        """
        self.cache = cache
        self.source = source
        self.archive = archive
        self._archive_ready = archive is None
        self._restore_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._state: OriginFetchState = "idle"
        self._total = 0
        self._completed = 0
        self._message = "Fetch a bounded batch to expand available country coverage."
        self._history: str | None = None
        self._closed = False

    async def restore(self) -> None:
        """Restore the configured private checkpoint before accepting lookups."""
        async with self._restore_lock:
            if self.archive is not None and not self._archive_ready:
                await self._restore_archive(self.archive)

    async def _restore_archive(self, archive: OriginArchive) -> None:
        try:
            entries = await archive.restore()
            await self.cache.install(entries)
        except OriginCacheError:
            self._message = "Could not restore the durable Artist Map checkpoint."
            return
        self._archive_ready = True

    def status(self) -> OriginFetchStatus:
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
        return OriginFetchStatus(
            self._state,
            self.source.configured,
            self._total,
            self._completed,
            message,
            catalog.snapshot,
            len(catalog.entries),
            self._history,
            not bool(catalog.message) and self._archive_ready,
            self.archive is not None,
        )

    def start(self, request: OriginFetchRequest) -> OriginFetchStatus:
        """Start one bounded batch after the HTTP boundary selects its artists.

        Args:
            request: Artist names captured from a pinned listening selection.

        Returns:
            Accepted progress or the already-running batch without duplication.

        Raises:
            OriginSourceError: Configuration is missing or the resource is closed.
            ValueError: The batch exceeds the fixed twenty-five-artist bound.
        """
        if len(request.artists) > 25:
            raise ValueError("Choose at most twenty-five artists per lookup batch.")
        return self._start(request)

    def start_backfill(self, request: OriginFetchRequest) -> OriginFetchStatus:
        """Start the durable backlog for a pinned, unfiltered history.

        Args:
            request: Missing artist identities from the complete history generation.

        Returns:
            Progress for the owned, resumable lookup.
        """
        if self.archive is None or not self._archive_ready:
            raise OriginSourceError("Durable Artist Map storage is unavailable.")
        catalog = self.cache.current()
        completed = {item.artist_key for item in catalog.entries}
        missing = tuple(item for item in request.artists if item.key not in completed)
        if len(completed) + len(missing) > ORIGIN_BACKFILL_LIMIT:
            raise OriginSourceError(
                "This library exceeds the durable Artist Map limit."
            )
        return self._start(OriginFetchRequest(missing, request.history_snapshot))

    def _start(self, request: OriginFetchRequest) -> OriginFetchStatus:
        if self._closed or not self.source.configured or not self._archive_ready:
            raise OriginSourceError(
                "Public MusicBrainz country lookup is not configured."
            )
        if self._task is not None and not self._task.done():
            return self.status()
        self._total = len(request.artists)
        self._completed = 0
        self._history = request.history_snapshot
        self._state = "running"
        self._message = (
            "Fetching public country metadata. Temporary failures retry automatically."
        )
        self._task = asyncio.create_task(self._run(request), name="listening-origins")
        return self.status()

    async def _run(self, request: OriginFetchRequest) -> None:
        try:
            await self._fetch(request)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._message = (
                "Lookup cancelled; completed cached observations are retained."
            )
            raise
        except OriginSourceError as error:
            self._state = "error"
            self._message = f"{error} Completed country lookups are saved."
        except OriginCacheError as error:
            self._state = "error"
            self._message = str(error)
        else:
            self._state = "complete"
            self._message = (
                "Lookup complete. Cached evidence describes current "
                "country associations."
            )

    async def _fetch(self, request: OriginFetchRequest) -> None:
        if self.archive is not None:
            await self._fetch_durable(request, self.archive)
            return
        for artist in request.artists:
            if self._completed:
                await asyncio.sleep(REQUEST_INTERVAL)
            metadata = await self.source.fetch(artist)
            await self._save(metadata)

    async def _fetch_durable(
        self, request: OriginFetchRequest, archive: OriginArchive
    ) -> None:
        for offset in range(0, len(request.artists), ORIGIN_CHECKPOINT_SIZE):
            batch = request.artists[offset : offset + ORIGIN_CHECKPOINT_SIZE]
            await self._complete_checkpoint(batch, archive)

    async def _complete_checkpoint(
        self, batch: tuple[RankedEntity, ...], archive: OriginArchive
    ) -> None:
        pending: list[ArtistOriginMetadata] = []
        try:
            for artist in batch:
                pending.append(await self.source.fetch(artist))
                self._message = (
                    f"{self._completed + len(pending)}/{self._total} looked up. "
                    f"{self._completed} saved to durable storage."
                )
        finally:
            if pending:
                entries = await archive.checkpoint(tuple(pending))
                await self.cache.install(entries)
                self._completed += len(pending)

    async def _save(self, metadata: ArtistOriginMetadata) -> None:
        try:
            await self.cache.save(metadata)
        finally:
            if metadata in self.cache.current().entries:
                self._completed += 1

    def cancel(self) -> OriginFetchStatus:
        """Request cancellation while the concrete resource drains active work.

        Returns:
            Cancellation progress without discarding completed cached entries.
        """
        if (
            self._state == "running"
            and self._task is not None
            and not self._task.done()
        ):
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
