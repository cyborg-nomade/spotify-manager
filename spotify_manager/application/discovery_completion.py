"""Promotion and unfollowing after a discovery artist finishes review."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.new_kids_state import assessment_from_record
from spotify_manager.application.new_kids_state import track_from_record
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.ports.discovery_execution import DiscoveryEffects
from spotify_manager.application.ports.discovery_execution import (
    DiscoveryExecutionPresentation,
)
from spotify_manager.domain.discovery import CatalogTrack


@dataclass(frozen=True)
class ReviewArtist:
    """Logical artist credit retained throughout one review transition.

    Args:
        identifier: Logical artist identifier, possibly a composer.
        name: Original artist display name.
    """

    identifier: str
    name: str


@dataclass
class DiscoveryCompletion:
    """Own completion routing and run-scoped destination membership projections.

    Args:
        access: Original playlist, follow and local-mirror boundaries.
        presentation: Original effect renderer.
        state: Mutable complete review namespace.
        year: Original invocation year.
        newfoundland: Configured Newfoundland destination.
        unlucky: Configured Unlucky Ones destination.
        dry_run: Whether to project effects without remote writes.
        memberships: Run-scoped destination artist and track sets.
    """

    access: DiscoveryEffects
    presentation: DiscoveryExecutionPresentation
    state: dict[str, object]
    year: int
    newfoundland: str
    unlucky: str
    dry_run: bool
    memberships: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)

    def finish(self, artist: ReviewArtist, plan: dict[str, object]) -> None:
        """Route a saved completion assessment and unfollow when required.

        Args:
            artist: Logical artist under review.
            plan: Original saved completion plan.

        Raises:
            NewKidsStateError: The saved assessment or track is malformed.
            NewKidsError: A qualifying artist has no representative marker.
        """
        assessment = assessment_from_record(plan.get("assessment"))
        composer = track_from_record(plan.get("composer_destination_track"))
        if assessment.top_liked_track is not None and assessment.qualifies:
            self._promote(artist, assessment, composer)
            return
        if assessment.top_liked_track is not None:
            target = composer or assessment.top_liked_track
            self._destination(artist, target, self.unlucky, "Unlucky Ones")
        self._unfollow(artist)

    def _promote(
        self,
        artist: ReviewArtist,
        assessment: ArtistAssessment,
        composer: CatalogTrack | None,
    ) -> None:
        target = composer or assessment.representative_track
        if target is None:
            raise NewKidsError(
                f"{artist.name} qualifies for promotion, but "
                "Spotify returned no primary-artist representative track."
            )
        great = self.access.great_playlist(self.state, self.dry_run)
        self._destination(artist, target, great, f"Great Discoveries {self.year}")
        self._destination(artist, target, self.newfoundland, "Newfoundland")

    def _destination(
        self,
        artist: ReviewArtist,
        target: CatalogTrack,
        playlist: str | None,
        label: str,
    ) -> None:
        if playlist is None:
            self.presentation.future_artist_added(artist.name, label, target.name)
            return
        if playlist not in self.memberships:
            self.memberships[playlist] = self.access.membership(playlist)
        artist_ids, track_ids = self.memberships[playlist]
        if artist.identifier in artist_ids:
            return
        if not self.dry_run:
            self.access.append(playlist, target, f"adding {artist.name} to {label}")
        artist_ids.add(artist.identifier)
        track_ids.add(target.spotify_id)
        self.presentation.artist_added(artist.name, label, self.dry_run)

    def _unfollow(self, artist: ReviewArtist) -> None:
        if not self.access.followed(artist.identifier, artist.name):
            return
        if not self.dry_run:
            self.access.unfollow(artist.identifier, artist.name)
            self.access.remove_local_artist(artist.identifier)
        self.presentation.artist_unfollowed(artist.name, self.dry_run)
