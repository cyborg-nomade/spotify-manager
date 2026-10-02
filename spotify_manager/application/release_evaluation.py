"""Shared live release evaluation over already observed ordered track facts."""

from spotify_manager.domain.albums import assess_album
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus


def evaluate_release(
    release: ReleaseCandidate, tracks: tuple[ReleaseTrack, ...], liked: dict[str, bool]
) -> AlbumEvaluation:
    """Apply the existing half-liked keep rule and preserve the validated result model.

    Args:
        release: Selected release whose canonical tracks are being evaluated.
        tracks: Ordered tracks within the active canonical endpoint.
        liked: Previously observed live memberships; absent IDs remain unliked.

    Returns:
        Original live evaluation, including per-track values and cache indicators.
    """
    liked_count = sum(liked.get(track.spotify_id, False) for track in tracks)
    assessment = assess_album(len(tracks), liked_count, 0.5)
    return AlbumEvaluation(
        album_name=release.name,
        album_id=release.spotify_id,
        artist_name=release.primary_artist_name,
        total_tracks=len(tracks),
        liked_tracks=liked_count,
        required_liked_tracks=assessment.required_liked_tracks,
        liked_ratio=assessment.liked_ratio,
        threshold=0.5,
        decision=assessment.decision,
        tracks=_track_statuses(tracks, liked),
        source="spotify-live",
        from_cache=False,
    )


def _track_statuses(
    tracks: tuple[ReleaseTrack, ...], liked: dict[str, bool]
) -> list[AlbumTrackLikedStatus]:
    statuses = []
    for track in tracks:
        statuses.append(
            AlbumTrackLikedStatus(
                name=track.name,
                uri=track.uri,
                liked=liked.get(track.spotify_id, False),
                spotify_id=track.spotify_id,
            )
        )
    return statuses


def evaluate_catalog_release(
    release: RankedRelease, tracks: tuple[CatalogTrack, ...], liked: dict[str, bool]
) -> AlbumEvaluation:
    """Evaluate discovery catalog values through the original shared album rule.

    Args:
        release: Selected ranked discovery release.
        tracks: Complete observed release tracks, including guest credits.
        liked: Shared live memberships, treating absent IDs as unliked.

    Returns:
        Original public live evaluation with catalog-only metadata omitted.
    """
    candidate = ReleaseCandidate(
        release.spotify_id,
        release.uri,
        release.name,
        release.release_type,
        release.release_date,
        release.total_tracks,
        release.primary_artist_id,
        release.primary_artist_name,
    )
    observed = []
    for track in tracks:
        observed.append(
            ReleaseTrack(
                track.spotify_id,
                track.uri,
                track.name,
                track.disc_number,
                track.track_number,
            )
        )
    return evaluate_release(candidate, tuple(observed), liked)
