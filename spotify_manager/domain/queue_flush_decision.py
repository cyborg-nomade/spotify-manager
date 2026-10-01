"""Choose Queue advancement, promotion and rejection from already observed facts."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.queue_fill import first_unliked


type FlushAction = Literal["advance", "promote", "unlucky", "unfollow", "blocked"]


@dataclass(frozen=True)
class QueueDecision:
    """One original Queue decision before or after promotion-marker resolution.

    Args:
        action: Original advancement, promotion or rejection decision.
        target: Original selected marker, absent while promotion needs resolution.
        reason: Original user-facing decision explanation.
    """

    action: FlushAction
    target: CatalogTrack | None
    reason: str


@dataclass(frozen=True)
class QueuePlan:
    """Original complete plan facts accepted before Queue effects.

    Args:
        action: Original resolved plan action.
        source_uris: Original ordered source URIs.
        target: Original optional destination marker.
        target_release: Original optional promotion release name.
        top_tracks: Original bounded top-track count.
        top_liked_tracks: Original liked top-track count.
        total_liked_tracks: Original liked primary-catalog count.
        reason: Original decision explanation.
    """

    action: FlushAction
    source_uris: list[str]
    target: CatalogTrack | None
    target_release: str | None
    top_tracks: int
    top_liked_tracks: int
    total_liked_tracks: int
    reason: str


def _source_index(tracks: tuple[CatalogTrack, ...], source: str) -> int:
    for index, track in enumerate(tracks):
        if track.spotify_id == source:
            return index
    return -1


def choose_queue_action(
    source: str,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
    total_liked: int,
    top_liked_track: CatalogTrack | None,
) -> QueueDecision:
    """Retain original six-catalog and end-of-window five-top promotion thresholds.

    Args:
        source: Original current marker identity, possibly absent from the window.
        tracks: Original bounded top tracks in source order.
        liked: Original top membership, with missing identities unliked.
        total_liked: Original assessment's liked primary-catalog count.
        top_liked_track: Original assessment's optional rejection marker.

    Returns:
        Original decision before resolving an eligible promotion marker.
    """
    next_track = first_unliked(tracks[_source_index(tracks, source) + 1 :], liked)
    if total_liked >= 6:
        return QueueDecision(
            "promote", None, "six liked tracks in the primary-artist catalog"
        )
    if next_track is None and sum(liked.values()) >= 5:
        return QueueDecision(
            "promote", None, "five liked tracks in the Spotify top ten"
        )
    if next_track is not None:
        return QueueDecision(
            "advance",
            next_track,
            "next unliked primary-artist track in the Spotify top ten",
        )
    if top_liked_track is not None:
        return QueueDecision(
            "unlucky",
            top_liked_track,
            "top-ten window ended below the promotion threshold",
        )
    return QueueDecision(
        "unfollow", None, "top-ten window ended without any liked tracks"
    )


def resolved_promotion(reason: str, target: CatalogTrack | None) -> QueueDecision:
    """Retain original blocked behavior when no eligible top-album marker exists.

    Args:
        reason: Original promotion threshold explanation.
        target: Original first eligible preferred-release marker, when present.

    Returns:
        Original promote or blocked decision and explanation.
    """
    if target is not None:
        return QueueDecision("promote", target, reason)
    return QueueDecision(
        "blocked", None, f"{reason}, but no eligible top album marker was found"
    )


def first_primary_marker(
    tracks: tuple[CatalogTrack, ...], artist: str
) -> CatalogTrack | None:
    """Retain the first original primary-credit marker in release order.

    Args:
        tracks: Original ordered release tracks.
        artist: Original requested primary artist.

    Returns:
        Original first primary marker or no marker.
    """
    for track in tracks:
        if track.primary_artist_id == artist:
            return track
    return None
