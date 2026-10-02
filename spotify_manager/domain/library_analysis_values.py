"""Stable library identities, analysis outcomes and clean pause signals."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from typing import Protocol


AnalysisMode = Literal["async", "sync", "mirrors"]
ResourceName = Literal["albums", "tracks", "artists"]
MirrorRefreshMode = Literal["incremental", "full"]


class LibraryIdentity(Protocol):
    """Describe original library identity without depending on external file models."""

    @property
    def spotify_id(self) -> str:
        """Read the original model's Spotify identity.

        Returns:
            Original complete Spotify identity, including empty values.
        """
        ...


@dataclass(frozen=True)
class ResourceCounts:
    """Describe original raw sizes, unique membership differences and growth.

    Args:
        total: Original complete post-analysis size, including duplicates.
        removed: Original removed-identity count.
        added: Original added-identity count.
        growth: Original percentage growth, using one for an empty baseline.
    """

    total: int
    removed: int
    added: int
    growth: float


@dataclass(frozen=True)
class AnalysisCounts:
    """Describe original complete library statistics independent of wire models.

    Args:
        albums: Original saved-album statistics.
        tracks: Original liked-track statistics.
        artists: Original followed-artist statistics.
        avg_albums_per_artists: Original integer album average.
        avg_liked_tracks_per_artists: Original integer track average.
    """

    albums: ResourceCounts
    tracks: ResourceCounts
    artists: ResourceCounts
    avg_albums_per_artists: int
    avg_liked_tracks_per_artists: int


ALBUM_PAGE_LIMIT = 50
TRACK_PAGE_LIMIT = 10
ARTIST_PAGE_LIMIT = 10
ARTIST_DIRECT_MAX_PAGES = 25
ARTIST_VERIFICATION_BATCH_LIMIT = 40
ARTIST_VERIFICATION_MAX_ATTEMPTS = 3
RECONCILIATION_STABLE_PASSES = 2
OFFSET_RECONCILIATION_STABLE_PAGES = {
    "albums": 2,
    "tracks": 3,
}


@dataclass(frozen=True)
class RetryNotice:
    """One scheduled retry after a transient Spotify failure.

    Args:
        http_status: Original transient status or none for transport failures.
        operation: Original visible request description.
        attempt: Original one-based attempt.
        delay_seconds: Original capped scheduled wait.
    """

    http_status: int | None
    operation: str
    attempt: int
    delay_seconds: int


@dataclass(frozen=True)
class ResourceSyncSummary:
    """Final source and diff counts for one generated file.

    Args:
        resource: Original resource identity.
        source: Original source authority.
        previous: Original pre-analysis size.
        current: Original post-analysis size.
        added: Original added-identity count.
        removed: Original removed-identity count.
        skipped: Original skipped raw-row count.
    """

    resource: ResourceName
    source: str
    previous: int
    current: int
    added: int
    removed: int
    skipped: int = 0


@dataclass(frozen=True)
class LibrarySyncSummary:
    """Final outcome of one completed library analysis.

    Args:
        run_id: Original sortable run identity.
        mode: Original output family.
        backup_dir: Original accepted undo snapshot location.
        resources: Original ordered resource outcomes.
    """

    run_id: str
    mode: AnalysisMode
    backup_dir: str
    resources: tuple[ResourceSyncSummary, ...]


class LibrarySyncError(RuntimeError):
    """Base exception for an analysis that cannot safely publish output."""


class LibraryAnalysisCancelledError(LibrarySyncError):
    """Raised after a user requests a clean, checkpointed stop."""


class IncompleteLiveResourceError(LibrarySyncError):
    """Raised when Spotify returns a structurally incomplete page sequence."""


class _FollowedArtistsEndpointUnavailableError(RuntimeError):
    """Signal that cursor discovery should switch to verified fallback."""


class LibrarySyncRestoreError(LibrarySyncError):
    """Raised when a requested analysis backup cannot be restored."""


RetryWait = Callable[[RetryNotice], bool]
