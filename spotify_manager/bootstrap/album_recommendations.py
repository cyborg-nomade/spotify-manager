"""Compose Sauvignon album observation with existing Spotify and retry helpers."""

from datetime import date
from functools import partial

from spotipy import Spotify

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.routines import sauvignon as legacy


def _search(
    spotify: Spotify,
    retry: legacy.RetryCall,
    candidate: FoundArtCandidate,
) -> tuple[legacy.SpotifyAlbumOption, ...]:
    return legacy.search_candidate_albums(spotify, candidate, retry)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def gather_albums(
    spotify: Spotify,
    candidates: tuple[FoundArtCandidate, ...],
    excluded: set[AlbumKey],
    existing: set[str],
    maximum: int,
    week: date,
    retry: legacy.RetryCall,
    progress: legacy.ProgressCallback | None,
) -> tuple[AlbumRecommendation, ...]:
    """Bind independent album gathering to original catalog and retry boundaries.

    Args:
        spotify: Caller-owned Spotify client.
        candidates: Original ordered ranked track pool.
        excluded: Original heard and previously added album keys.
        existing: Original represented destination album identities.
        maximum: Original Python-slice limit on considered tracks.
        week: Original effective listening week.
        retry: Existing caller-owned retry behavior.
        progress: Optional original candidate presenter.

    Returns:
        Original ranked album recommendations after all observations succeed.

    Raises:
        SauvignonSpotifyError: Existing catalog observations are unusable.
    """
    workflow = AlbumGathering(
        partial(_search, spotify, retry), partial(_progress, progress)
    )
    return workflow.run(candidates, excluded, existing, maximum, week)
