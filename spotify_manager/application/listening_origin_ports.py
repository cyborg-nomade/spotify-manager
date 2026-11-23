"""Explicit metadata read/cache resources and enrichment progress values."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.application.listening_provider_error import ListeningProviderError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import OriginCatalog
from spotify_manager.domain.listening_values import RankedEntity


type OriginFetchState = Literal[
    "idle", "running", "cancelling", "cancelled", "complete", "error"
]


class OriginSourceError(ListeningProviderError):
    """A provider lookup failed without invalidating available cached metadata."""


class OriginCacheError(RuntimeError):
    """Derived country metadata could not be read or persisted."""


class OriginSource(Protocol):
    """Read public country associations through one concrete provider boundary."""

    @property
    def configured(self) -> bool:
        """Return whether provider configuration permits explicit lookups."""
        ...

    async def fetch(self, artist: RankedEntity) -> ArtistOriginMetadata:
        """Read one identity-checked public artist response.

        Args:
            artist: Requested display name and analytics identity.

        Returns:
            Dated metadata or an explicitly unresolved identity.

        Raises:
            OriginSourceError: A safe provider or transport failure.
        """
        ...


class OriginCache(Protocol):
    """Retain complete metadata generations without canonical-data writes."""

    def current(self) -> OriginCatalog:
        """Return the latest complete cached metadata generation."""
        ...

    def acquire(self, snapshot: str) -> OriginCatalog:
        """Pin one available immutable metadata generation.

        Args:
            snapshot: Explicit generation identity.

        Returns:
            Complete generation retained by the caller.

        Raises:
            ListeningVersionError: The requested generation expired.
        """
        ...

    async def save(self, metadata: ArtistOriginMetadata) -> None:
        """Persist one completed lookup before publishing a new generation.

        Args:
            metadata: Identity-checked, dated lookup outcome.

        Raises:
            OriginCacheError: Persistence failed; previous complete data remains.
        """
        ...


@dataclass(frozen=True)
class OriginFetchRequest:
    """Capture a bounded batch independently of later filter changes.

    Args:
        artists: At most twenty-five named artists selected by a fixed domain rule.
        history_snapshot: Source selection that produced the requested batch.
    """

    artists: tuple[RankedEntity, ...]
    history_snapshot: str


@dataclass(frozen=True)
class OriginFetchStatus:
    """Describe explicit enrichment work separately from history availability.

    Args:
        state: Current batch lifecycle.
        configured: Whether public provider reads are configured.
        total: Number of requested artists.
        completed: Number of complete lookup outcomes saved.
        message: Data-free progress, recovery or cancellation explanation.
        metadata_snapshot: Last complete metadata generation.
        cached_artists: Number of cached lookup outcomes.
        history_snapshot: Source generation that selected this batch.
        cache_available: Whether derived storage initialized successfully.
    """

    state: OriginFetchState
    configured: bool
    total: int
    completed: int
    message: str
    metadata_snapshot: str
    cached_artists: int
    history_snapshot: str | None
    cache_available: bool
