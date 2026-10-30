"""Script complete catalog responses while measuring requests and overlap."""

import asyncio
from dataclasses import dataclass
from dataclasses import field


def catalog_track(identifier: str) -> dict[str, object]:
    """Supply the exact fields used by the unchanged primary-credit parser.

    Args:
        identifier: Synthetic track identity.

    Returns:
        A primary-artist track row without external configuration or file I/O.
    """
    return {"id": identifier, "artists": [{"id": "artist"}]}


def album_reply(identifiers: list[str]) -> dict[str, object]:
    """Return one primary-credit track for each requested album.

    Args:
        identifiers: Ordered album identities, retaining duplicates.

    Returns:
        Complete synthetic album batch with no dependent track pages.
    """
    albums: list[object] = []
    for identifier in identifiers:
        tracks = {"items": [catalog_track(identifier)], "next": None}
        albums.append({"id": identifier, "tracks": tracks})
    return {"albums": albums}


@dataclass
class CatalogPages:
    """Count real awaited read boundaries without network or wall-clock thresholds.

    Args:
        replies: Optional exact batch responses.
        failures: Optional original exceptions keyed by the requested batch.
        continuations: Ordered responses for dependent track pagination.
        latency: Optional simulated I/O delay used only by the offline benchmark.
    """

    replies: dict[tuple[str, ...], object] = field(default_factory=dict)
    failures: dict[tuple[str, ...], BaseException] = field(default_factory=dict)
    continuations: list[object] = field(default_factory=list)
    latency: float = 0
    calls: list[tuple[str, ...]] = field(default_factory=list, init=False)
    pages: list[object] = field(default_factory=list, init=False)
    active: int = field(default=0, init=False)
    peak: int = field(default=0, init=False)

    async def albums(self, identifiers: list[str]) -> object:
        """Observe one batch and yield once so independent readers can overlap.

        Args:
            identifiers: Ordered request identities.

        Returns:
            Scripted response or a complete deterministic catalog batch.

        Raises:
            BaseException: The exact configured upstream failure.
        """
        key = tuple(identifiers)
        self.calls.append(key)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.latency)
            if key in self.failures:
                raise self.failures[key]
            return self.replies.get(key, album_reply(identifiers))
        finally:
            self.active -= 1

    async def next_tracks(self, page: object) -> object:
        """Read a continuation only after its own preceding response is consumed.

        Args:
            page: Original validated page containing its next link.

        Returns:
            Next scripted page.
        """
        self.pages.append(page)
        value = self.continuations.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def next_object(self, page: object) -> object:
        """Reject unrelated object-page requests.

        Args:
            page: Unexpected page.

        Raises:
            AssertionError: The catalog operation used the wrong pagination path.
        """
        raise AssertionError(page)

    async def release_page(self, artist: str, offset: int) -> object:
        """Reject discovery of IDs not already supplied to this catalog read.

        Args:
            artist: Unexpected artist.
            offset: Unexpected discovery offset.

        Raises:
            AssertionError: The catalog operation tried to discover another page.
        """
        raise AssertionError((artist, offset))


def release_ids(count: int) -> list[str]:
    """Build ordered unique synthetic album IDs.

    Args:
        count: Number of distinct IDs.

    Returns:
        Stable input order for result and request-budget assertions.
    """
    return [str(index) for index in range(count)]


@dataclass
class HeldCatalogPages(CatalogPages):
    """Hold a window so completion order and cancellation can be controlled.

    Args:
        entered: Notification that four reads have been admitted.
        releases: Independent response-release signals keyed by batch.
        completed: Actual completion order of admitted reads.
    """

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    releases: dict[tuple[str, ...], asyncio.Event] = field(default_factory=dict)
    completed: list[tuple[str, ...]] = field(default_factory=list)

    async def albums(self, identifiers: list[str]) -> object:
        """Hold a request until its own response or cancellation is delivered.

        Args:
            identifiers: Original ordered album batch.

        Returns:
            Complete synthetic response.
        """
        key = tuple(identifiers)
        self.calls.append(key)
        self.active += 1
        self.peak = max(self.peak, self.active)
        if len(self.calls) == 4:
            self.entered.set()
        try:
            if key in self.failures:
                raise self.failures[key]
            await self.releases.setdefault(key, asyncio.Event()).wait()
            return album_reply(identifiers)
        finally:
            self.active -= 1
            self.completed.append(key)
