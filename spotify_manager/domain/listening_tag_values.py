"""Current community-tag observations and explicitly allocated listening views."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.listening_values import RankedEntity


type TagState = Literal["tagged", "empty", "unresolved"]


@dataclass(frozen=True)
class CommunityTag:
    """Retain a source tag label with stable identity.

    Args:
        key: Normalized label identity.
        name: Original community label, not an asserted genre classification.
    """

    key: str
    name: str


@dataclass(frozen=True)
class ArtistTagMetadata:
    """Record one dated, identity-checked public artist-tag response.

    Args:
        artist_key: Requested analytics artist identity.
        artist_name: Requested display spelling.
        resolved_name: Artist name reported by the provider.
        state: Verified tags, verified empty tags, or unresolved artist identity.
        tags: Up to ten ranked unique source labels.
        fetched_at: Aware UTC retrieval time, not historical genre evidence.
        source_url: Public provider page without credentials.
    """

    artist_key: str
    artist_name: str
    resolved_name: str
    state: TagState
    tags: tuple[CommunityTag, ...]
    fetched_at: str
    source_url: str


@dataclass(frozen=True, eq=False)
class TagCatalog:
    """Pin an immutable derived metadata generation separately from history.

    Args:
        snapshot: Content identity for complete cached observations.
        entries: Complete, validated current observations.
        message: Data-free cache availability or recovery explanation.
    """

    snapshot: str
    entries: tuple[ArtistTagMetadata, ...]
    message: str = ""


@dataclass(frozen=True)
class TagOptions:
    """Specify allocation and a bounded artist-evidence page.

    Args:
        per_artist: Primary tag or equal allocation among up to three tags.
        tag: Optional stable tag identity, including unknown.
        search: Display artist substring.
        page: One-based evidence page.
        limit: Maximum returned artists.
    """

    per_artist: Literal[1, 3] = 3
    tag: str | None = None
    search: str = ""
    page: int = 1
    limit: int = 25


@dataclass(frozen=True)
class TagArtist:
    """Connect selected actual plays to their current metadata evidence.

    Args:
        artist: Selected artist count and share.
        state: Cached lookup outcome or metadata missing.
        tags: Source labels before allocation truncation.
        fetched_at: Retrieval date when looked up.
        source_url: Credential-free public artist page.
    """

    artist: RankedEntity
    state: TagState | Literal["missing"]
    tags: tuple[CommunityTag, ...]
    fetched_at: str | None
    source_url: str | None


@dataclass(frozen=True)
class TagSeries:
    """Allocate complete selected play counts without double counting tags.

    Args:
        key: Tag identity, other, or unknown.
        name: Source display label or explicit residual category.
        counts: Aligned allocated plays, possibly fractional in three-tag mode.
    """

    key: str
    name: str
    counts: tuple[float, ...]


@dataclass(frozen=True)
class TagCoverage:
    """Keep actual listening and metadata availability separate.

    Args:
        plays: Exact selected scrobbles.
        tagged_plays: Actual plays from artists with verified available tags.
        artists: Distinct selected artist identities.
        tagged_artists: Artists with verified tags.
        looked_up_artists: Artists with any completed lookup outcome.
        empty_artists: Verified artists with no tags.
        unresolved_artists: Provider identities not safely corroborated.
    """

    plays: int
    tagged_plays: int
    artists: int
    tagged_artists: int
    looked_up_artists: int
    empty_artists: int
    unresolved_artists: int


@dataclass(frozen=True)
class TagAnalysis:
    """Cache complete derived allocations before bounded evidence filtering.

    Args:
        periods: Chronological month labels, including empty months.
        series: Fixed top-eight tags, Other and Unknown.
        artists: Complete selected artist evidence.
        coverage: Exact listening and metadata coverage.
    """

    periods: tuple[str, ...]
    series: tuple[TagSeries, ...]
    artists: tuple[TagArtist, ...]
    coverage: TagCoverage


@dataclass(frozen=True)
class ListeningTags:
    """Present allocations with bounded supporting artists and applied options.

    Args:
        metadata_snapshot: Independently pinned cached metadata generation.
        periods: Calendar months for aligned series.
        series: Allocated counts preserving all selected plays.
        coverage: Actual listening and unknown-metadata coverage.
        items: Current bounded artist-evidence page.
        total: Artists matching the evidence filter.
        page: One-based page.
        limit: Requested page size.
        options: Actual applied allocation and evidence options.
        retrieved_from: Earliest cached lookup used by this selected history.
        retrieved_through: Latest cached lookup used by this selected history.
    """

    metadata_snapshot: str
    periods: tuple[str, ...]
    series: tuple[TagSeries, ...]
    coverage: TagCoverage
    items: tuple[TagArtist, ...]
    total: int
    page: int
    limit: int
    options: TagOptions
    retrieved_from: str | None
    retrieved_through: str | None
