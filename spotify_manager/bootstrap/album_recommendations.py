"""Compose Sauvignon album observation with existing Spotify and retry helpers."""

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.legacy.album_search import LegacyAlbumSearch
from spotify_manager.routines import sauvignon as legacy


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
        LegacyAlbumSearch(spotify, retry), OptionalMessages(progress)
    )
    return workflow
