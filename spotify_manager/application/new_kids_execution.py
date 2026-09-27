"""Execute one durable discovery plan, preserving effect and checkpoint order."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from spotify_manager.application.discovery_completion import DiscoveryCompletion
from spotify_manager.application.discovery_completion import ReviewArtist
from spotify_manager.application.discovery_library import DiscoveryLibraryReconciliation
from spotify_manager.application.new_kids_state import positive_int
from spotify_manager.application.new_kids_state import release_from_record
from spotify_manager.application.new_kids_state import result_from_plan
from spotify_manager.application.new_kids_state import track_from_record
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.ports.discovery_execution import DiscoveryEffects
from spotify_manager.application.ports.discovery_execution import (
    DiscoveryExecutionPresentation,
)
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass(frozen=True)
class ReviewTransition:
    """Accepted plan and its original decoded catalog values.

    Args:
        plan: Durable plan, retaining unknown fields and action values.
        action: Original required action string.
        release: Current release to reconcile.
        target_release: Optional next release.
        target: Optional replacement marker.
    """

    plan: dict[str, object]
    action: str
    release: RankedRelease
    target_release: RankedRelease | None
    target: CatalogTrack | None


def _transition(plan: dict[str, object]) -> ReviewTransition:
    action = str(plan["action"])
    release = release_from_record(plan["current_release"])
    target_release = (
        release_from_record(plan["target_release"])
        if plan.get("target_release") is not None
        else None
    )
    target = track_from_record(plan.get("target"))
    return ReviewTransition(plan, action, release, target_release, target)


@dataclass
class NewKidsExecution:
    """Apply saved review transitions and acknowledge them before result audit.

    Args:
        access: External playlist and follow effects.
        state_access: Existing namespace checkpoint boundary.
        library: Completed-release library reconciliation.
        completion: Artist promotion and unfollowing with shared memberships.
        presentation: Original accepted-effect messages.
        state: Mutable complete review namespace.
        live_ids: Shared live/projected source playlist membership.
        playlist_id: Review playlist identifier.
        label: Original review playlist display label.
        dry_run: Whether remote writes and progress checkpoints are suppressed.
        clock: Original UTC clock for separate artist and composer timestamps.
    """

    access: DiscoveryEffects
    state_access: RoutineState
    library: DiscoveryLibraryReconciliation
    completion: DiscoveryCompletion
    presentation: DiscoveryExecutionPresentation
    state: dict[str, object]
    live_ids: set[str]
    playlist_id: str
    label: str
    dry_run: bool
    clock: Callable[[], datetime]

    def execute(
        self,
        source: PlaylistTrack,
        artist: ReviewArtist,
        entry: dict[str, object],
        progress: dict[str, object],
        plan: dict[str, object],
    ) -> FlushResult:
        """Apply one transition in original library/playlist/progress order.

        Args:
            source: Original snapshotted marker.
            artist: Logical artist credit for this review.
            entry: Mutable durable run entry.
            progress: Mutable artist progress within the namespace.
            plan: Accepted saved or newly planned transition.

        Returns:
            Original result ready for the coordinator's completion audit.

        Raises:
            NewKidsStateError: A persisted plan contains invalid records.
            NewKidsError: A promotion lacks a representative marker.
        """
        transition = _transition(plan)
        if isinstance(plan.get("evaluation"), dict):
            evaluation = AlbumEvaluation.model_validate(plan["evaluation"])
            self.library.reconcile(transition.release, evaluation)
        self._destination(artist, transition)
        self._remove_source(source)
        self._complete(artist, entry, progress, transition)
        return result_from_plan(source, plan, self.dry_run, artist_name=artist.name)

    def _destination(self, artist: ReviewArtist, transition: ReviewTransition) -> None:
        if (
            transition.action in {"advance", "next_release"}
            and transition.target is not None
        ):
            self._advance(transition.target)
        elif transition.action == "finish":
            self.completion.finish(artist, transition.plan)

    def _advance(self, target: CatalogTrack) -> None:
        if target.spotify_id in self.live_ids:
            return
        if not self.dry_run:
            self.access.append(
                self.playlist_id, target, f"adding {target.name} to {self.label}"
            )
        self.live_ids.add(target.spotify_id)
        self.presentation.marker_added(target.name, self.dry_run)

    def _remove_source(self, source: PlaylistTrack) -> None:
        if source.spotify_id not in self.live_ids:
            return
        if not self.dry_run:
            self.access.remove(self.playlist_id, source, self.label)
        self.live_ids.discard(source.spotify_id)
        self.presentation.marker_removed(source.name, self.dry_run)

    def _complete(
        self,
        artist: ReviewArtist,
        entry: dict[str, object],
        progress: dict[str, object],
        transition: ReviewTransition,
    ) -> None:
        if self.dry_run:
            return
        if transition.action == "finish":
            self._forget_artist(artist.identifier)
        else:
            self._progress(artist.identifier, progress, transition)
        entry["status"] = "completed"
        self.state_access.save(self.state)

    def _forget_artist(self, artist_id: str) -> None:
        artists = self.state["artists"]
        assert isinstance(artists, dict)
        artists.pop(artist_id, None)
        routes = self.state.get("composer_routes")
        if isinstance(routes, dict):
            routes.pop(artist_id, None)

    def _progress(
        self, artist_id: str, progress: dict[str, object], transition: ReviewTransition
    ) -> None:
        if (
            transition.action == "next_release"
            and transition.target_release is not None
        ):
            progress["current_release_id"] = transition.target_release.spotify_id
        progress["prior_unliked_streak"] = positive_int(
            transition.plan.get("next_prior_unliked_streak")
        )
        progress["updated_at"] = self.clock().isoformat()
        routes = self.state.get("composer_routes")
        if not isinstance(routes, dict) or not transition.plan.get(
            "composer_playlist_id"
        ):
            return
        route = routes.get(artist_id)
        if isinstance(route, dict) and transition.target is not None:
            route["current_track_id"] = transition.target.spotify_id
            route["updated_at"] = self.clock().isoformat()
