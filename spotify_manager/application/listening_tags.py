"""Named cached-tag analysis and explicitly triggered bounded enrichment."""

import asyncio
from functools import lru_cache

from spotify_manager.application.listening_tag_ports import TagCache
from spotify_manager.application.listening_tag_ports import TagCacheError
from spotify_manager.application.listening_tag_ports import TagFetchRequest
from spotify_manager.application.listening_tag_ports import TagFetchState
from spotify_manager.application.listening_tag_ports import TagFetchStatus
from spotify_manager.application.listening_tag_ports import TagHistoryReads
from spotify_manager.application.listening_tag_ports import TagSource
from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_tag_values import ListeningTags
from spotify_manager.domain.listening_tag_values import TagAnalysis
from spotify_manager.domain.listening_tag_values import TagCatalog
from spotify_manager.domain.listening_tag_values import TagOptions
from spotify_manager.domain.listening_tags import analyze_tags
from spotify_manager.domain.listening_tags import present_tags
from spotify_manager.domain.listening_values import ListeningQuery


REQUEST_INTERVAL = 1.0


@lru_cache(maxsize=8)
def _analysis(
    index: TagHistoryReads, catalog: TagCatalog, query: ListeningQuery, size: int
) -> TagAnalysis:
    return analyze_tags(
        index.artist_plays(query),
        index.lifetimes(query, "artist"),
        catalog,
        query,
        size,
    )


def get_listening_tags(
    index: TagHistoryReads,
    catalog: TagCatalog,
    query: ListeningQuery,
    options: TagOptions,
) -> ListeningTags:
    """Analyze only cached metadata; rendering never requests live provider data.

    Args:
        index: Complete pinned listening generation.
        catalog: Independently pinned current community-tag observations.
        query: Validated listening dates and optional artist/rhythm filters.
        options: Allocation mode and bounded artist-evidence filters.

    Returns:
        Complete allocated totals, unknown coverage and a supporting artist page.
    """
    return present_tags(
        _analysis(index, catalog, query, options.per_artist), catalog, options
    )


class ListeningTagEnrichment:
    """Own one explicit lookup batch with direct named provider/cache calls.

    Args:
        cache: Complete, persistent derived metadata generations.
        source: Configured public artist-tag read resource.
    """

    def __init__(self, cache: TagCache, source: TagSource) -> None:
        """Bind the concrete resources and initialize an idle batch.

        Args:
            cache: Derived metadata resource, separate from canonical data.
            source: Public read provider; no account or playlist mutation API.
        """
        self.cache = cache
        self.source = source
        self._task: asyncio.Task[None] | None = None
        self._state: TagFetchState = "idle"
        self._total = 0
        self._completed = 0
        self._message = "Fetch a bounded batch to expand available tag coverage."
        self._history: str | None = None
        self._closed = False

    def status(self) -> TagFetchStatus:
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
            message = "Last.fm lookup is not configured; cached views remain available."
        if catalog.message:
            message += " " + catalog.message
        return TagFetchStatus(
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

    def start(self, request: TagFetchRequest) -> TagFetchStatus:
        """Start one bounded batch after the HTTP boundary selects its artists.

        Args:
            request: Artist names captured from a pinned listening selection.

        Returns:
            Accepted progress or the already-running batch without duplication.

        Raises:
            TagSourceError: Configuration is missing or the resource is closed.
            ValueError: The batch exceeds the fixed fifty-artist bound.
        """
        if self._closed or not self.source.configured:
            raise TagSourceError("Public Last.fm tag lookup is not configured.")
        if self._task is not None and not self._task.done():
            return self.status()
        if len(request.artists) > 50:
            raise ValueError("Choose at most fifty artists per lookup batch.")
        self._total = len(request.artists)
        self._completed = 0
        self._history = request.history_snapshot
        self._state = "running"
        self._message = "Fetching public artist tags; existing history stays available."
        self._task = asyncio.create_task(self._run(request), name="listening-tags")
        return self.status()

    async def _run(self, request: TagFetchRequest) -> None:
        try:
            await self._fetch(request)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._message = (
                "Lookup cancelled; completed cached observations are retained."
            )
            raise
        except TagSourceError, TagCacheError:
            self._state = "error"
            self._message = (
                "Tag lookup unavailable; completed metadata is retained. Retry later."
            )
        else:
            self._state = "complete"
            self._message = (
                "Lookup batch complete. Cached tags describe current community labels."
            )

    async def _fetch(self, request: TagFetchRequest) -> None:
        for artist in request.artists:
            if self._completed:
                await asyncio.sleep(REQUEST_INTERVAL)
            metadata = await self.source.fetch(artist)
            await self._save(metadata)

    async def _save(self, metadata: ArtistTagMetadata) -> None:
        try:
            await self.cache.save(metadata)
        finally:
            if metadata in self.cache.current().entries:
                self._completed += 1

    def cancel(self) -> TagFetchStatus:
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
