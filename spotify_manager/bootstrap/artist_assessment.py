"""Compose the New Kids/Queue 2 artist-completion use case."""

from spotipy import Spotify

from spotify_manager.application.artist_assessment import assess_artist
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.artist_assessment import (
    LegacyAssessmentCatalog,
)


def observe_artist_assessment(
    client: Spotify,
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    retry: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
) -> ArtistAssessment:
    """Bind the existing synchronous client and shared cache to the application.

    Args:
        client: Caller-owned Spotify client.
        artist_id: Primary artist being assessed.
        catalog: Original ordered catalog observations.
        retry: Existing retry and cancellation callback.
        track_cache: Shared mutable release-track cache for this run.

    Returns:
        Original completion assessment and representative marker choices.
    """
    return assess_artist(
        LegacyAssessmentCatalog(client, retry), artist_id, catalog, track_cache
    )
