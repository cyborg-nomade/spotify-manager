"""Current album-name evidence and independently cached representative artwork."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.listening_values import RankedEntity


type CoverState = Literal["ready", "no_cover", "unmatched", "ambiguous", "incomplete"]
type CoverEvidence = CoverState | Literal["missing"]


@dataclass(frozen=True)
class CoverCandidate:
    """Retain one exact title/artist-credit candidate without asserting identity.

    Args:
        mbid: MusicBrainz release-group identity.
        title: Original album title, preserving edition labels.
        artist: Complete credited artist name, including join phrases.
        description: Provider disambiguation.
    """

    mbid: str
    title: str
    artist: str
    description: str


@dataclass(frozen=True)
class CoverArtwork:
    """Identify the specific release and image representing a release group.

    Args:
        release_mbid: Cover Art Archive's representative release.
        image_id: Original archive image identifier.
        sha256: Content identity of the validated JPEG thumbnail.
        width: Encoded pixel width.
        height: Encoded pixel height.
    """

    release_mbid: str
    image_id: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class LastFmArtwork:
    """Keep an exact Last.fm catalogue match and its intact thumbnail identity.

    Args:
        source: Explicit provider attribution.
        page_url: Catalogue page derived from the exact artist and album names.
        sha256: Content identity of the validated thumbnail.
        width: Encoded pixel width.
        height: Encoded pixel height.
    """

    source: Literal["lastfm"]
    page_url: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class AlbumCoverMetadata:
    """Keep a dated bounded search separate from listening observations.

    Args:
        album_key: Requested history album identity.
        album_name: Original history title.
        artist_name: Original history artist context.
        state: Search/artwork outcome, without guessing ambiguous identities.
        candidates: Up to five distinct exact-name release groups.
        candidate_count: Complete exact-name count found in the bounded response.
        fetched_at: Aware current metadata retrieval instant.
        artwork: Representative artwork only for one complete name candidate.
    """

    album_key: str
    album_name: str
    artist_name: str
    state: CoverState
    candidates: tuple[CoverCandidate, ...]
    candidate_count: int
    fetched_at: str
    artwork: CoverArtwork | LastFmArtwork | None = None


@dataclass(frozen=True)
class CoverImage:
    """Retain immutable validated bytes under their content identity.

    Args:
        sha256: Digest binding the image to metadata.
        content: Bounded JPEG or PNG bytes outside the analytical JSON.
    """

    sha256: str
    content: bytes


@dataclass(frozen=True)
class CoverFetchResult:
    """Commit an observation and its optional image together.

    Args:
        metadata: Completed provider outcome.
        image: Validated bytes when metadata reports available artwork.
    """

    metadata: AlbumCoverMetadata
    image: CoverImage | None = None


@dataclass(frozen=True, eq=False)
class CoverCatalog:
    """Pin metadata and its image bytes independently of other explorer views.

    Args:
        snapshot: Complete metadata content identity.
        entries: Complete validated observations.
        images: Immutable image bytes retained for this exact generation.
        message: Safe derived-cache availability explanation.
    """

    snapshot: str
    entries: tuple[AlbumCoverMetadata, ...]
    images: tuple[CoverImage, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class QuiltOptions:
    """Choose a bounded ranked quilt while retaining album/artist context.

    Args:
        size: Maximum visible albums in a square layout.
        search: Title or artist substring; preserves accents and editions.
    """

    size: Literal[9, 16, 25, 49] = 16
    search: str = ""


@dataclass(frozen=True)
class QuiltAlbum:
    """Connect one actual ranked history album to optional current cover evidence.

    Args:
        album: Exact selected count/share and original display names.
        evidence: Cached outcome or never looked up.
        candidates: Original provider name candidates.
        candidate_count: Number found before the display bound.
        fetched_at: Retrieval time, independent of listening dates.
        artwork: Representative release artwork, when supported.
    """

    album: RankedEntity
    evidence: CoverEvidence
    candidates: tuple[CoverCandidate, ...]
    candidate_count: int
    fetched_at: str | None
    artwork: CoverArtwork | LastFmArtwork | None


@dataclass(frozen=True)
class QuiltOutcome:
    """Count one artwork outcome within the displayed quilt.

    Args:
        evidence: Lookup/artwork outcome.
        albums: Displayed album identities in this category.
        plays: Actual selected plays belonging to those albums.
    """

    evidence: CoverEvidence
    albums: int
    plays: int


@dataclass(frozen=True)
class QuiltCoverage:
    """Separate whole-selection counts, displayed listening and cover availability.

    Args:
        plays: All selected plays, including blank albums.
        album_plays: Plays with recorded album names.
        missing_album_plays: Plays lacking an album name.
        albums: All selected named album identities.
        matching_albums: Albums matching the optional quilt search.
        shown_plays: Actual plays represented by visible tiles.
        artwork_albums: Visible albums with supported artwork.
        artwork_plays: Visible plays with supported artwork.
        outcomes: Complete displayed-album and play reconciliation.
    """

    plays: int
    album_plays: int
    missing_album_plays: int
    albums: int
    matching_albums: int
    shown_plays: int
    artwork_albums: int
    artwork_plays: int
    outcomes: tuple[QuiltOutcome, ...]


@dataclass(frozen=True)
class ListeningQuilt:
    """Present a bounded ranked cover quilt with complete scope and provenance.

    Args:
        metadata_snapshot: Independent immutable cover generation.
        items: Ranked visible albums, including placeholders.
        options: Applied size and search.
        coverage: Full selection and displayed artwork counts.
        retrieved_from: Earliest displayed lookup instant.
        retrieved_through: Latest displayed lookup instant.
    """

    metadata_snapshot: str
    items: tuple[QuiltAlbum, ...]
    options: QuiltOptions
    coverage: QuiltCoverage
    retrieved_from: str | None
    retrieved_through: str | None
