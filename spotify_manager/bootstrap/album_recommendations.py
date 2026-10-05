"""Compose Sauvignon album observation with existing Spotify and retry helpers."""

from functools import partial

from spotipy import Spotify

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.routines import sauvignon as legacy


def _search(
    spotify: Spotify,
    retry: legacy.RetryCall,
    candidate: FoundArtCandidate,
) -> tuple[legacy.SpotifyAlbumOption, ...]:
    from spotify_manager.routines.sauvignon import search_candidate_albums

    return search_candidate_albums(spotify, candidate, retry)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def album_gathering(
    spotify: Spotify, retry: legacy.RetryCall, progress: legacy.ProgressCallback | None
) -> AlbumGathering:
    """Construct the invocation dependencies without executing the use case.

    Args:
        spotify: Caller-owned Spotify client.
        retry: Existing caller-owned retry behavior.
        progress: Optional original candidate presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    workflow = AlbumGathering(
        partial(_search, spotify, retry), partial(_progress, progress)
    )
    return workflow
