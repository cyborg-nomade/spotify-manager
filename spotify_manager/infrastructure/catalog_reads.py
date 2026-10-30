"""Overlap only complete, independent album batches within one catalog read."""

import asyncio
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.infrastructure import lookup_catalog
from spotify_manager.infrastructure import lookup_records
from spotify_manager.infrastructure.lookup_catalog import LookupPages
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import LegacyControlError


_READ_WINDOW = 4
_MAX_CACHED_BATCHES = 32


@dataclass(frozen=True)
class AlbumResponse:
    """Distinguish returned upstream data from an exception raised by a read.

    Args:
        value: Original unvalidated response, including malformed non-JSON overrides.
    """

    value: object


def album_windows(identifiers: list[str], batch_size: int) -> Iterator[list[list[str]]]:
    """Group the existing endpoint batches into bounded independent read windows.

    Args:
        identifiers: Already discovered album IDs in their original encounter order.
        batch_size: Existing supported album endpoint batch size.

    Yields:
        At most four batches, retaining all IDs and duplicates in each request.

    Raises:
        ValueError: The original range step is zero.
    """
    for start in range(0, len(identifiers), batch_size * _READ_WINDOW):
        stop = min(start + batch_size * _READ_WINDOW, len(identifiers))
        batches = []
        for offset in range(start, stop, batch_size):
            batches.append(identifiers[offset : offset + batch_size])
        yield batches


@dataclass
class AlbumCatalogReads:
    """Own a bounded catalog snapshot before any live membership or user decision.

    Args:
        pages: One invocation's explicit album and dependent track-page resource.
    """

    pages: LookupPages
    _batches: OrderedDict[tuple[str, ...], asyncio.Task[AlbumResponse]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    async def primary_tracks(
        self, artist: str, identifiers: list[str], batch_size: int
    ) -> list[str]:
        """Read independent batches concurrently, then decode in original order.

        Args:
            artist: Primary artist used by the unchanged track-credit rule.
            identifiers: Complete already-discovered album sequence.
            batch_size: Existing supported endpoint batch size.

        Returns:
            Unique primary-credit track IDs in their original encounter order.

        Raises:
            BaseException: The original first failure in catalog traversal order.
        """
        try:
            return await self._primary_tracks(artist, identifiers, batch_size)
        finally:
            self._batches.clear()

    async def _primary_tracks(
        self, artist: str, identifiers: list[str], batch_size: int
    ) -> list[str]:
        tracks: dict[str, None] = {}
        for batches in album_windows(identifiers, batch_size):
            await self._collect(batches, artist, tracks)
        return list(tracks)

    async def _collect(
        self, batches: list[list[str]], artist: str, tracks: dict[str, None]
    ) -> None:
        tasks = []
        for batch in batches:
            tasks.append(self._batch(batch))
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for response in responses:
            albums = _accepted_albums(response)
            await lookup_catalog.collect_album_tracks(
                albums, self.pages, artist, tracks
            )

    def _batch(self, identifiers: list[str]) -> asyncio.Task[AlbumResponse]:
        key = tuple(identifiers)
        if key not in self._batches:
            self._batches[key] = asyncio.create_task(self._read_batch(identifiers))
        self._batches.move_to_end(key)
        if len(self._batches) > _MAX_CACHED_BATCHES:
            self._batches.popitem(last=False)
        return self._batches[key]

    async def _read_batch(self, identifiers: list[str]) -> AlbumResponse:
        # Restore process control at the caller, rather than stop a child task's loop.
        with LegacyControl():
            return AlbumResponse(await self.pages.albums(identifiers))


def _accepted_albums(response: AlbumResponse | BaseException) -> list[object]:
    if isinstance(response, LegacyControlError):
        raise response.control
    if isinstance(response, BaseException):
        raise response
    return lookup_records.album_batch(response.value)
