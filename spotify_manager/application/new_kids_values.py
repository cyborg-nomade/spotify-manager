"""Original public values for New Kids and Queue 2 application workflows."""

from dataclasses import dataclass

from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class ArtistAssessment:
    """Live completion criteria for one artist.

    Args:
        liked_tracks: Unique liked primary-artist track count.
        saved_releases: Saved count across all observed membership statuses.
        total_releases: Catalog entry count, retaining duplicate releases.
        liked_primary_tracks: Unique liked primary-artist track count.
        total_primary_tracks: Unique primary-artist catalog track count.
        qualifies: Whether at least one existing promotion criterion matches.
        reasons: Original promotion messages in evaluation order.
        representative_track: First primary-artist track in preferred chronology.
        top_liked_track: First liked top track, or the catalog popularity fallback.
    """

    liked_tracks: int
    saved_releases: int
    total_releases: int
    liked_primary_tracks: int
    total_primary_tracks: int
    qualifies: bool
    reasons: tuple[str, ...]
    representative_track: CatalogTrack | None
    top_liked_track: CatalogTrack | None
