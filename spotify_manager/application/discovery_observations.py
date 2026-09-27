"""Run-scoped discovery observations shared by ordinary and composer review paths."""

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from spotify_manager.application.artist_assessment import AssessmentCatalog
from spotify_manager.application.artist_assessment import assess_artist
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.release_history import ReleaseHistoryCatalog
from spotify_manager.application.release_history import played_releases
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex


class DiscoveryCatalog(AssessmentCatalog, ReleaseHistoryCatalog, Protocol):
    """Supply original discovery, membership and owned-playlist observations."""

    def ranked(self, artist_id: str) -> tuple[RankedRelease, ...]:
        """Observe ranked catalog candidates for one artist.

        Args:
            artist_id: Logical artist being reviewed.

        Returns:
            Original canonical release observations in discovery order.
        """

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe ordered works-playlist markers.

        Args:
            playlist_id: Accepted owned works playlist.

        Returns:
            Original playable markers, retaining duplicates.
        """


@dataclass
class DiscoveryObservations:
    """Reuse only catalog reads cached by the original review invocation.

    Args:
        access: Original external observation boundaries.
        history: Current-year normalized listening evidence.
        release_limit: Existing studio preference and review completion count.
        studio_minimum: Existing studio distinct-title completion minimum.
        catalogs: Accepted artist catalogs, keyed by logical artist ID.
        release_tracks: Shared accepted catalog tracks, including empty responses.
        liked: Shared accepted live memberships.
        works: Accepted works-playlist observations, including empty responses.
    """

    access: DiscoveryCatalog
    history: AnnualScrobbleIndex
    release_limit: int = 4
    studio_minimum: int = 3
    catalogs: dict[str, tuple[RankedRelease, ...]] = field(default_factory=dict)
    release_tracks: dict[str, tuple[CatalogTrack, ...]] = field(default_factory=dict)
    liked: dict[str, bool] = field(default_factory=dict)
    works: dict[str, tuple[PlaylistTrack, ...]] = field(default_factory=dict)

    def catalog(self, artist_id: str) -> tuple[RankedRelease, ...]:
        """Observe an artist catalog once per invocation.

        Args:
            artist_id: Logical artist identifier.

        Returns:
            Cached or newly accepted ranked releases.
        """
        if artist_id not in self.catalogs:
            self.catalogs[artist_id] = self.access.ranked(artist_id)
        return self.catalogs[artist_id]

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Observe one release's tracks once per invocation.

        Args:
            release: Selected catalog release.

        Returns:
            Cached or newly accepted tracks, including empty observations.
        """
        if release.spotify_id not in self.release_tracks:
            self.release_tracks[release.spotify_id] = self.access.tracks(release)
        return self.release_tracks[release.spotify_id]

    def composer_tracks(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe a works playlist once per invocation.

        Args:
            playlist_id: Accepted owned-playlist ID.

        Returns:
            Cached or newly accepted original marker sequence.
        """
        if playlist_id not in self.works:
            self.works[playlist_id] = self.access.playlist(playlist_id)
        return self.works[playlist_id]

    def memberships(self, ids: list[str]) -> None:
        """Populate missing live memberships at the original request boundary.

        Args:
            ids: Original ordered requests, retaining duplicates.
        """
        self.access.likes(ids, self.liked)

    def assessment(
        self, artist_id: str, catalog: tuple[RankedRelease, ...]
    ) -> ArtistAssessment:
        """Observe completion criteria using the shared accepted catalog-track cache.

        Args:
            artist_id: Logical artist being assessed.
            catalog: Original catalog, including any prepended source release.

        Returns:
            Original live completion assessment.
        """
        return assess_artist(self.access, artist_id, catalog, self.release_tracks)

    def played(self, catalog: tuple[RankedRelease, ...]) -> tuple[RankedRelease, ...]:
        """Check current-year completion using the original shared caches.

        Args:
            catalog: Existing review-catalog preference selection.

        Returns:
            Completed release entries in original order, retaining duplicates.
        """
        return played_releases(
            self.access,
            catalog,
            self.history,
            self.release_tracks,
            self.liked,
            release_limit=self.release_limit,
            studio_minimum=self.studio_minimum,
        )
