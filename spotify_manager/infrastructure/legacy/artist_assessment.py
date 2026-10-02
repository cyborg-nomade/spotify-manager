"""Bind artist-completion observations to the original synchronous SDK helpers."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.routines import new_kids as legacy


@dataclass(frozen=True)
class LegacyAssessmentCatalog:
    """Retain original loaders, conservative batches and retry descriptions.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry and cancellation boundary.
    """

    client: Spotify
    retry: RetryCall

    def saved(self, ids: list[str]) -> dict[str, bool]:
        """Observe saved release membership.

        Args:
            ids: Original catalog identifiers, including duplicates.

        Returns:
            Live statuses accepted by the existing batch parser.
        """
        return legacy._assessment_saved(self.client, ids, self.retry)

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read a selected release's original ordered tracks.

        Args:
            release: Requested release.

        Returns:
            Parsed playable tracks with primary credits.
        """
        return legacy.load_release_tracks(self.client, release, self.retry)

    def liked(self, ids: list[str], *, top: bool = False) -> dict[str, bool]:
        """Observe likes through the original context-specific SDK call site.

        Args:
            ids: Requested track identifiers.
            top: Whether observations belong to top-track selection.

        Returns:
            Live statuses accepted by the existing batch parser.
        """
        reader = legacy._assessment_top_liked if top else legacy._assessment_liked
        return reader(self.client, ids, self.retry)

    def top_tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Read eligible artist top tracks.

        Args:
            artist_id: Artist being assessed.

        Returns:
            Original primary-credit-filtered top-track sequence.
        """
        _ranks, tracks = legacy.load_top_track_data(self.client, artist_id, self.retry)
        return tracks

    def popularities(self, ids: list[str]) -> dict[str, int]:
        """Read popularity using the original fallback batching.

        Args:
            ids: Unique liked primary-artist track identifiers.

        Returns:
            Accepted popularity values.
        """
        return legacy._catalog_track_popularities(self.client, ids, self.retry)
