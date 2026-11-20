"""Evidence and coverage for comparisons with published Spotify collections."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntityLifetime


type LibraryMatch = Literal["name_match", "unmatched", "ambiguous", "unavailable"]


@dataclass(frozen=True)
class MirrorSource:
    """Describe one published collection independently of listening dates.

    Args:
        kind: Artist follows, saved albums, or liked tracks.
        state: Whether the complete publication was verified and decoded.
        published_at: Publication timestamp, not historical membership time.
        sha256: Expected complete artifact identity when published.
        source: Publication provenance label.
        entries: Unique Spotify identities in a verified publication.
        message: Data-free coverage explanation.
    """

    kind: EntityKind
    state: Literal["ready", "missing", "error"]
    published_at: str | None
    sha256: str | None
    source: str | None
    entries: int
    message: str


@dataclass(frozen=True)
class LibraryEntry:
    """Retain exact names and a validated Spotify identity as match evidence.

    Args:
        kind: Collection dimension.
        key: Analytics-normalized artist or artist/title identity.
        name: Published artist, album, or track display name.
        artist: Published artist context, empty for artist follows.
        uri: Validated Spotify URI; source album IDs are never substituted.
    """

    kind: EntityKind
    key: str
    name: str
    artist: str
    uri: str


@dataclass(frozen=True, eq=False)
class LibraryCatalog:
    """Own one complete immutable comparison generation.

    Args:
        snapshot: Version token including source identities and availability.
        revision: Single pinned durable manifest revision.
        sources: Explicit coverage of all three independent collections.
        entries: Only verified complete artifacts contribute name evidence.
    """

    snapshot: str
    revision: str
    sources: tuple[MirrorSource, ...]
    entries: tuple[LibraryEntry, ...]


@dataclass(frozen=True)
class LibraryOptions:
    """Bound a current-collection comparison over the selected history.

    Args:
        kind: Collection dimension.
        status: Evidence category or all categories.
        minimum_plays: Inclusive selected-play threshold.
        search: Case-insensitive display name or artist substring.
        page: One-based page.
        limit: Maximum returned rows.
    """

    kind: EntityKind = "album"
    status: LibraryMatch | Literal["all"] = "all"
    minimum_plays: int = 1
    search: str = ""
    page: int = 1
    limit: int = 25


@dataclass(frozen=True)
class LibraryComparisonItem:
    """Pair recorded counts with bounded and explicitly uncertain evidence.

    Args:
        history: Selected recorded plays and their actual bounds.
        status: Exact-name evidence, never a verified cross-service identity.
        candidates: At most five distinct matching Spotify identities.
        candidate_count: Full distinct candidate count before display bounding.
    """

    history: EntityLifetime
    status: LibraryMatch
    candidates: tuple[LibraryEntry, ...]
    candidate_count: int


@dataclass(frozen=True)
class LibraryCoverage:
    """Count one disjoint evidence category before search and status filtering.

    Args:
        status: Evidence category.
        entities: Distinct historical entities meeting the play threshold.
        plays: Recorded plays for those entities.
    """

    status: LibraryMatch
    entities: int
    plays: int


@dataclass(frozen=True)
class LibraryComparison:
    """Present a bounded comparison with both source identities intact.

    Args:
        library_snapshot: Pinned mirror generation separate from history.
        revision: Pinned publication manifest revision.
        source: Selected collection's provenance and availability.
        coverage: Disjoint counts before status/search filtering.
        items: One deterministic page of evidence rows.
        total: Number of rows after search/status filtering.
        page: One-based page.
        limit: Requested page size.
        options: Applied comparison options, independent of unsubmitted UI edits.
    """

    library_snapshot: str
    revision: str
    source: MirrorSource
    coverage: tuple[LibraryCoverage, ...]
    items: tuple[LibraryComparisonItem, ...]
    total: int
    page: int
    limit: int
    options: LibraryOptions
