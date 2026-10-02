"""Bind Queue planning to original synchronous catalog and assessment seams."""

from dataclasses import dataclass

from spotipy import Spotify

from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
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
        _, tracks = legacy.new_kids.load_top_track_data(
            self.spotify, artist, self.retry
        )
        return tracks

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Retain original top membership validation and retry text.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original liked statuses.
        """
        return legacy._liked_statuses(self.spotify, tracks, self.retry)

    def catalog(self, artist: str) -> tuple[RankedRelease, ...]:
        """Read original ranked catalog after top membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ranked releases in source order.
        """
        return legacy.new_kids.load_ranked_catalog(self.spotify, artist, self.retry)

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
        return legacy.new_kids.assess_artist(
            self.spotify, artist, catalog, self.retry, cache
        )

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read uncached preferred-release tracks with original paging and retry.

        Args:
            release: Original requested preferred release.

        Returns:
            Original ordered catalog tracks.
        """
        return legacy.new_kids.load_release_tracks(self.spotify, release, self.retry)
