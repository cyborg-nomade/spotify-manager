"""Stable recommendations result serialization."""

from spotify_manager.interfaces.http.models.recommendations import (
    FoundArtSelectionResult,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonSelectionResult,
)
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.routines import sauvignon


def found_art_selection_result(
    result: found_art.FoundArtResult,
) -> FoundArtSelectionResult:
    """Convert one Found Art result into its stable API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    spotify_match = None
    track_similarity = None
    if result.match is not None:
        album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - {album}"
        )
        track_similarity = result.match.track_similarity
    return FoundArtSelectionResult(
        artist=result.candidate.artist,
        track=result.candidate.track,
        score=result.candidate.score,
        best_match=result.candidate.best_match,
        supporting_seeds=list(result.candidate.supporting_seeds),
        base_rank=result.candidate.base_rank,
        weekly_rank=result.candidate.weekly_rank,
        spotify_match=spotify_match,
        track_similarity=track_similarity,
        action=result.action,
    )


def sauvignon_selection_result(
    result: sauvignon.SauvignonResult,
) -> SauvignonSelectionResult:
    """Convert one Sauvignon album recommendation for stable web polling.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    album = result.album
    return SauvignonSelectionResult(
        artist=result.recommendation.artist,
        album=result.recommendation.album,
        score=result.recommendation.score,
        best_match=result.recommendation.best_match,
        supporting_tracks=list(result.recommendation.supporting_tracks),
        base_rank=result.recommendation.base_rank,
        weekly_rank=result.recommendation.weekly_rank,
        spotify_album=album.album if album is not None else None,
        spotify_album_id=album.spotify_id if album is not None else None,
        release_type=album.release_type if album is not None else None,
        release_date=album.release_date if album is not None else None,
        first_track=result.first_track.name if result.first_track is not None else None,
        action=result.action,
    )
