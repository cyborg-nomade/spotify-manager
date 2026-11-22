"""Dated country-association evidence without asserting cross-service identity."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.listening_values import RankedEntity


type OriginState = Literal["matched", "unmatched", "ambiguous", "incomplete"]
type OriginEvidence = Literal[
    "single_country",
    "multiple_countries",
    "no_country",
    "unmatched",
    "ambiguous",
    "incomplete",
    "missing",
]


@dataclass(frozen=True)
class OriginCandidate:
    """Retain one exact-name MusicBrainz candidate and its reported places.

    Args:
        mbid: Provider artist identity, not an asserted history identity.
        name: Original provider artist name.
        description: Provider disambiguation text.
        artist_type: Person, group or other source type.
        area: Main associated area, not necessarily birth or formation origin.
        begin_area: Reported birth or formation place, when supplied.
        countries: Distinct reported country codes; never inferred from tags.
    """

    mbid: str
    name: str
    description: str
    artist_type: str
    area: str
    begin_area: str
    countries: tuple[str, ...]


@dataclass(frozen=True)
class ArtistOriginMetadata:
    """Capture a bounded name search, including incomplete or ambiguous evidence.

    Args:
        artist_key: Requested normalized history identity.
        artist_name: Requested display spelling.
        state: Exact-name search outcome; matched remains name evidence.
        candidates: Up to five distinct exact-name provider candidates.
        candidate_count: Exact-name candidates found in the bounded response.
        fetched_at: Aware retrieval instant for current source metadata.
    """

    artist_key: str
    artist_name: str
    state: OriginState
    candidates: tuple[OriginCandidate, ...]
    candidate_count: int
    fetched_at: str


@dataclass(frozen=True, eq=False)
class OriginCatalog:
    """Pin current country observations independently of history and tag data.

    Args:
        snapshot: Complete metadata content identity.
        entries: Complete validated cache contents.
        message: Safe cache availability explanation.
    """

    snapshot: str
    entries: tuple[ArtistOriginMetadata, ...]
    message: str = ""


@dataclass(frozen=True)
class OriginOptions:
    """Filter supporting artists without changing the complete map totals.

    Args:
        country: Optional reported two-letter country code.
        evidence: Specific evidence outcome or all artists.
        search: Artist display-name substring.
        page: One-based artist page.
        limit: Maximum returned artists.
    """

    country: str | None = None
    evidence: OriginEvidence | Literal["all"] = "all"
    search: str = ""
    page: int = 1
    limit: int = 25


@dataclass(frozen=True)
class OriginArtist:
    """Connect actual selected plays with bounded geographic name evidence.

    Args:
        artist: Exact historical count and share.
        evidence: Single country, multiple, absent, or unresolved metadata.
        candidates: Bounded original provider candidates.
        candidate_count: Distinct exact-name matches found before truncation.
        fetched_at: Retrieval date, independent of listening dates.
    """

    artist: RankedEntity
    evidence: OriginEvidence
    candidates: tuple[OriginCandidate, ...]
    candidate_count: int
    fetched_at: str | None


@dataclass(frozen=True)
class CountryListening:
    """Count artists with one exact-name candidate and one reported country.

    Args:
        code: Original provider country code.
        plays: Actual selected plays; each qualifying play appears once.
        artists: Distinct qualifying history artists.
        share: Share of all selected plays, including unknown metadata.
    """

    code: str
    plays: int
    artists: int
    share: float


@dataclass(frozen=True)
class OriginCoverage:
    """Preserve complete history and separate unresolved geographic evidence.

    Args:
        plays: All selected scrobbles.
        artists: All selected artist identities.
        country_plays: Plays with one candidate and one geographic country code.
        country_artists: Artists supporting the country totals.
        looked_up_artists: Artists with any completed lookup.
        outcomes: Complete artist and play totals for each evidence category.
    """

    plays: int
    artists: int
    country_plays: int
    country_artists: int
    looked_up_artists: int
    outcomes: tuple[OriginOutcome, ...]


@dataclass(frozen=True)
class OriginOutcome:
    """Reconcile one evidence category with actual listening counts.

    Args:
        evidence: Category identity.
        artists: Distinct selected artists.
        plays: Their complete selected scrobbles.
    """

    evidence: OriginEvidence
    artists: int
    plays: int


@dataclass(frozen=True)
class ListeningOrigins:
    """Present complete country totals and bounded supporting evidence.

    Args:
        metadata_snapshot: Independently pinned country metadata generation.
        countries: Complete country totals before evidence filtering.
        available_countries: Codes across all candidates, including ambiguous evidence.
        coverage: Complete selected listening and lookup coverage.
        items: Current artist page.
        total: Artists matching applied evidence/search filters.
        page: One-based page.
        limit: Requested maximum rows.
        options: Actual applied filters.
        retrieved_from: Earliest relevant lookup date.
        retrieved_through: Latest relevant lookup date.
    """

    metadata_snapshot: str
    countries: tuple[CountryListening, ...]
    available_countries: tuple[str, ...]
    coverage: OriginCoverage
    items: tuple[OriginArtist, ...]
    total: int
    page: int
    limit: int
    options: OriginOptions
    retrieved_from: str | None
    retrieved_through: str | None
