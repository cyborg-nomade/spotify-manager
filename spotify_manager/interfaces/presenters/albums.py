"""Present a typed album review using the existing CLI and HTTP response model."""

from spotify_manager.application.album_review import AlbumReview
from spotify_manager.application.music import Track
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus


def _track_status(track: Track, liked: bool) -> AlbumTrackLikedStatus:
    return AlbumTrackLikedStatus(
        name=track.name, uri=track.uri, liked=liked, spotify_id=track.spotify_id
    )


def album_evaluation(review: AlbumReview) -> AlbumEvaluation:
    """Build the unchanged public live-album result.

    Args:
        review: Current ordered observations and the domain retention decision.

    Returns:
        The existing Pydantic response, including source and cache metadata.
    """
    tracks = []
    for track, liked in zip(review.tracks, review.liked, strict=True):
        tracks.append(_track_status(track, liked))
    return AlbumEvaluation(
        album_name=review.album.name,
        album_id=review.album.spotify_id,
        artist_name=review.album.artist,
        total_tracks=len(review.tracks),
        liked_tracks=sum(review.liked),
        required_liked_tracks=review.assessment.required_liked_tracks,
        liked_ratio=review.assessment.liked_ratio,
        threshold=review.threshold,
        decision=review.assessment.decision,
        tracks=tracks,
        source="spotify-live",
        from_cache=False,
    )
