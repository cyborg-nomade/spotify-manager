"""Explicit metadata read/cache resources and enrichment progress values."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.application.listening_provider_error import ListeningProviderError
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_values import RankedEntity


type CoverFetchState = Literal[
    "idle", "running", "cancelling", "cancelled", "complete", "error"
]


class CoverSourceError(ListeningProviderError):
    """A provider lookup failed without invalidating available cached metadata."""


class CoverCacheError(RuntimeError):
    """Derived cover metadata could not be read or persisted."""


class CoverSource(Protocol):
    """Read public album artwork through one concrete provider boundary."""

    @property
    def configured(self) -> bool:
        """Return whether provider configuration permits explicit lookups.

        Returns:
            Whether new public searches may be started.
        """
        ...

    async def fetch(self, album: RankedEntity) -> CoverFetchResult:
        """Read one identity-checked public album response.

        Args:
            album: Requested display name and analytics identity.

        Returns:
            Dated metadata or an explicitly unresolved identity.

        Raises:
            CoverSourceError: A safe provider or transport failure.
        """
        ...


class QuickCoverSource(Protocol):
    """Find an attributed cover or leave the album for the fallback pass."""

    async def fetch(self, album: RankedEntity) -> CoverFetchResult | None:
        """Return a corroborated cover, or none if the fallback is needed."""
        ...


class CoverCache(Protocol):
    """Retain complete metadata generations without canonical-data writes."""

    def current(self) -> CoverCatalog:
        """Return the latest complete cached metadata generation.

        Returns:
            Complete metadata and its bound immutable image bytes.
        """
        ...

    def acquire(self, snapshot: str) -> CoverCatalog:
        """Pin one available immutable metadata generation.

        Args:
            snapshot: Explicit generation identity.

        Returns:
            Complete generation retained by the caller.

        Raises:
            ListeningVersionError: The requested generation expired.
        """
        ...

    async def save(self, metadata: CoverFetchResult) -> None:
        """Persist one completed lookup before publishing a new generation.

        Args:
            metadata: Identity-checked, dated lookup outcome.

        Raises:
            CoverCacheError: Persistence failed; previous complete data remains.
        """
        ...


@dataclass(frozen=True)
class CoverFetchRequest:
    """Capture a bounded batch independently of later filter changes.

    Args:
        albums: At most ten named albums selected by a fixed domain rule.
        history_snapshot: Source selection that produced the requested batch.
    """

    albums: tuple[RankedEntity, ...]
    history_snapshot: str


@dataclass(frozen=True)
class CoverFetchStatus:
    """Describe explicit enrichment work separately from history availability.

    Args:
        state: Current batch lifecycle.
        configured: Whether public provider reads are configured.
        total: Number of requested albums.
        completed: Number of complete lookup outcomes saved.
        message: Data-free progress, recovery or cancellation explanation.
        metadata_snapshot: Last complete metadata generation.
        cached_albums: Number of cached lookup outcomes.
        history_snapshot: Source generation that selected this batch.
        cache_available: Whether derived storage initialized successfully.
    """

    state: CoverFetchState
    configured: bool
    total: int
    completed: int
    message: str
    metadata_snapshot: str
    cached_albums: int
    history_snapshot: str | None
    cache_available: bool
