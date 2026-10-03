"""Bind Queue planning to original synchronous catalog and assessment seams."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.artist_assessment import assess_artist
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.artist_assessment import (
    LegacyAssessmentCatalog,
)
from spotify_manager.routines import the_queue as legacy


@dataclass(frozen=True)
class LegacyQueuePlanning:
    """Retain original caller-owned client, retry and shared assessment behavior.

    Args:
        spotify: Original caller-owned Spotify client.
        retry: Original retry boundary.
    """

    spotify: Spotify
    retry: legacy.RetryCall

    def top(self, artist: str) -> tuple[CatalogTrack, ...]:
        """Read original ordered top tracks before membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ordered eligible top tracks.
        """
        from spotify_manager.routines.new_kids import load_top_track_data

        _, tracks = load_top_track_data(self.spotify, artist, self.retry)
        return tracks

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Retain original top membership validation and retry text.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original liked statuses.
        """
        from spotify_manager.routines.the_queue import _liked_statuses

        return _liked_statuses(self.spotify, tracks, self.retry)

    def catalog(self, artist: str) -> tuple[RankedRelease, ...]:
        """Read original ranked catalog after top membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ranked releases in source order.
        """
        from spotify_manager.routines.new_kids import load_ranked_catalog

        return load_ranked_catalog(self.spotify, artist, self.retry)

    def assessment(
        self,
        artist: str,
        catalog: tuple[RankedRelease, ...],
        cache: dict[str, tuple[CatalogTrack, ...]],
    ) -> ArtistAssessment:
        """Retain shared assessment and its caller-owned cache population.

        Args:
            artist: Original primary artist identity.
            catalog: Original ranked releases.
            cache: Caller-owned original observed release tracks.

        Returns:
            Original complete live artist assessment.
        """
        return assess_artist(
            LegacyAssessmentCatalog(self.spotify, self.retry), artist, catalog, cache
        )

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read uncached preferred-release tracks with original paging and retry.

        Args:
            release: Original requested preferred release.

        Returns:
            Original ordered catalog tracks.
        """
        from spotify_manager.routines.new_kids import load_release_tracks

        return load_release_tracks(self.spotify, release, self.retry)
