"""Construct matching stages without searching or requesting operator decisions."""

from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.application.manual_matching import CatalogMatchInteraction
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.infrastructure.manual_album_catalog import SpotifyManualAlbums
from spotify_manager.infrastructure.manual_track_catalog import SpotifyManualTracks


def tracks(
    client: SpotifyClient, interaction: CatalogMatchInteraction | None, retry: Retry
) -> ManualTrackMatching | None:
    """Compose an optional track fallback for an interactive feature invocation.

    Args:
        client: Caller-owned Spotify client.
        interaction: Choice and cancellation owner, absent for compatibility calls.
        retry: Caller-owned request policy.

    Returns:
        Configured application stage, or none for noninteractive calls.
    """
    if interaction is None:
        return None
    return ManualTrackMatching(
        SpotifyManualTracks(client, retry, interaction), interaction, interaction
    )


def albums(
    client: SpotifyClient, interaction: CatalogMatchInteraction | None, retry: Retry
) -> ManualAlbumMatching | None:
    """Compose an optional album fallback for an interactive feature invocation.

    Args:
        client: Caller-owned Spotify client.
        interaction: Choice and cancellation owner, absent for compatibility calls.
        retry: Caller-owned request policy.

    Returns:
        Configured application stage, or none for noninteractive calls.
    """
    if interaction is None:
        return None
    return ManualAlbumMatching(
        SpotifyManualAlbums(client, retry, interaction), interaction, interaction
    )
