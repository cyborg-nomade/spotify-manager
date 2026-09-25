"""Artist promotion criteria with explicit facts and stable reason ordering."""

from dataclasses import dataclass
from enum import StrEnum


class PromotionReason(StrEnum):
    """Existing user-visible reasons in their evaluation order."""

    LIKED_TRACKS = "18 liked tracks"
    SAVED_RELEASES = "3 saved releases"
    ALL_ALBUMS = "all albums saved"
    ALL_TRACKS = "all tracks liked"


@dataclass(frozen=True)
class ArtistFacts:
    """Observed library facts used by the completed-artist promotion rules.

    Args:
        liked_tracks: Primary-artist liked-track count.
        total_tracks: Primary-artist catalog track count.
        saved_releases: Count across all observed saved statuses.
        album_saved_statuses: Saved statuses for catalog albums only.
    """

    liked_tracks: int
    total_tracks: int
    saved_releases: int
    album_saved_statuses: tuple[bool, ...]


def promotion_reasons(facts: ArtistFacts) -> tuple[PromotionReason, ...]:
    """Evaluate every matching promotion reason without imposing route overrides.

    Args:
        facts: Library observations gathered by the routine.

    Returns:
        Matching reasons in legacy order; zero-like route overrides stay outside.
    """
    reasons = []
    if facts.liked_tracks >= 18:
        reasons.append(PromotionReason.LIKED_TRACKS)
    if facts.saved_releases >= 3:
        reasons.append(PromotionReason.SAVED_RELEASES)
    if facts.album_saved_statuses and all(facts.album_saved_statuses):
        reasons.append(PromotionReason.ALL_ALBUMS)
    if facts.total_tracks > 0 and facts.liked_tracks == facts.total_tracks:
        reasons.append(PromotionReason.ALL_TRACKS)
    return tuple(reasons)
