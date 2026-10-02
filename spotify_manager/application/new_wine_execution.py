"""Execute a durable New Wine transition without changing effect order."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime

from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.new_wine_plans import record_evaluation
from spotify_manager.application.new_wine_state import release_from_record
from spotify_manager.application.new_wine_state import result_from_plan
from spotify_manager.application.new_wine_state import track_from_record
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.ports.new_wine import NewWineAccess
from spotify_manager.application.ports.new_wine import NewWinePresentation
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation


@dataclass
class WineTransition:
    """Reconstructed durable plan fields for one execution attempt.

    Args:
        source: Original marker.
        entry: Durable entry owning the plan and completion status.
        plan: Mutable original plan, including unknown fields.
        release: Selected release.
        target: Planned replacement, if present.
        continuation_release: Optional follow-up release.
        continuation_target: Optional follow-up marker.
        action: Original action, retaining tolerant unknown-action behavior.
        album_unsaved: Persisted or newly accepted album-removal flag.
    """

    source: PlaylistTrack
    entry: dict[str, object]
    plan: dict[str, object]
    release: ReleaseCandidate
    target: ReleaseTrack | None
    continuation_release: ReleaseCandidate | None
    continuation_target: ReleaseTrack | None
    action: str
    album_unsaved: bool


def _transition(
    source: PlaylistTrack, entry: dict[str, object], plan: dict[str, object]
) -> WineTransition:
    release = release_from_record(plan["release"])
    target = track_from_record(plan.get("target"))
    continuation = (
        release_from_record(plan["continuation_release"])
        if plan.get("continuation_release") is not None
        else None
    )
    continuation_target = track_from_record(plan.get("continuation_target"))
    return WineTransition(
        source,
        entry,
        plan,
        release,
        target,
        continuation,
        continuation_target,
        str(plan["action"]),
        bool(plan.get("album_unsaved")),
    )


@dataclass
class WineExecution:
    """Own ordered effects and membership projections for one flush invocation.

    Args:
        access: External playlist, album, mirror and checkpoint boundaries.
        observations: Run-scoped catalog and membership observations.
        destination: Configured New Wine playlist.
        sauvignon: Configured Sauvignon playlist.
        destination_ids: Mutable live/projected New Wine membership.
        sauvignon_ids: Mutable live/projected Sauvignon membership.
        state: Complete mutable namespace.
        progress: Persisted per-marker streak records.
        dry_run: Whether remote effects and checkpoints are suppressed.
        presentation: Effect messages rendered after their accepted boundaries.
        clock: Original UTC clock for progress records.
    """

    access: NewWineAccess
    observations: WineObservations
    destination: str
    sauvignon: str
    destination_ids: set[str]
    sauvignon_ids: set[str]
    state: dict[str, object]
    progress: dict[str, object]
    dry_run: bool
    presentation: NewWinePresentation
    clock: Callable[[], datetime]

    def execute(
        self, source: PlaylistTrack, entry: dict[str, object], plan: dict[str, object]
    ) -> FlushResult:
        """Apply one saved plan and checkpoint completion before returning its result.

        Args:
            source: Original marker.
            entry: Its mutable durable entry.
            plan: Accepted saved or newly planned transition.

        Returns:
            Original public result ready for audit.
        """
        transition = _transition(source, entry, plan)
        self._missing_evaluation(transition)
        if transition.action == "sauvignon":
            self._save_qualified(transition)
        self._primary(transition)
        self._continuation(transition)
        self._remove_source(source)
        self._save_progress(transition)
        return result_from_plan(
            source, plan, dry_run=self.dry_run, album_unsaved=transition.album_unsaved
        )

    def checkpoint(self) -> None:
        """Save the namespace at the original boundary during real execution."""
        if not self.dry_run:
            self.access.save(self.state)

    def _missing_evaluation(self, transition: WineTransition) -> None:
        if (
            transition.action != "sauvignon"
            or transition.plan.get("evaluation") is not None
        ):
            return
        tracks = self.observations.tracks(transition.release)
        count = transition.plan.get("canonical_track_count")
        if isinstance(count, int):
            tracks = tracks[:count]
        self.observations.memberships(tracks)
        record_evaluation(
            transition.plan,
            evaluate_release(transition.release, tracks, self.observations.liked),
        )
        transition.entry["plan"] = transition.plan
        self.checkpoint()

    def _save_qualified(self, transition: WineTransition) -> None:
        release = transition.release
        evaluation = AlbumEvaluation.model_validate(transition.plan["evaluation"])
        if evaluation.decision != "keep":
            self.presentation.not_kept(release, evaluation)
            return
        saved = self.access.saved(release)
        if not self.dry_run and not saved:
            self.access.save_album(release)
        if not self.dry_run:
            self.access.mirror_album(release)
        self.presentation.kept(release, evaluation, saved, self.dry_run)

    def _primary(self, transition: WineTransition) -> None:
        if (
            not self.dry_run
            and transition.source.spotify_id not in self.destination_ids
        ):
            self.presentation.resumed(transition.source)
            return
        if transition.action == "advance" and transition.target is not None:
            self._advance(transition.target)
            return
        if (
            transition.action == "sauvignon"
            and transition.target is not None
            and transition.target.spotify_id not in self.sauvignon_ids
        ):
            self._sauvignon(transition.target, transition.release)
            return
        if transition.action == "drop" and bool(transition.plan.get("should_unsave")):
            self._unsave(transition)

    def _advance(self, target: ReleaseTrack) -> None:
        if target.spotify_id in self.destination_ids:
            return
        if not self.dry_run:
            self.access.append(self.destination, target)
        self.destination_ids.add(target.spotify_id)
        self.presentation.advanced(target, self.dry_run)

    def _sauvignon(self, target: ReleaseTrack, release: ReleaseCandidate) -> None:
        if not self.dry_run:
            self.access.append(self.sauvignon, target)
        self.sauvignon_ids.add(target.spotify_id)
        self.presentation.sauvignon(release, self.dry_run)

    def _unsave(self, transition: WineTransition) -> None:
        evaluation = AlbumEvaluation.model_validate(transition.plan["evaluation"])
        saved = self.access.saved(transition.release, removing=True)
        if self.dry_run:
            transition.album_unsaved = saved
        elif not transition.album_unsaved and saved:
            self._remove_album(transition, evaluation)
        self.presentation.removed_album(
            transition.release, evaluation, saved, self.dry_run
        )

    def _remove_album(
        self, transition: WineTransition, evaluation: AlbumEvaluation
    ) -> None:
        self.access.unsave_album(transition.release)
        self.access.remove_mirror_album(transition.release)
        reason = f"new_wine_{transition.plan.get('drop_reason') or 'drop'}"
        self.access.removed_audit(transition.release, evaluation, reason)
        transition.album_unsaved = True
        transition.plan["album_unsaved"] = True
        self.access.save(self.state)

    def _continuation(self, transition: WineTransition) -> None:
        release, target = (
            transition.continuation_release,
            transition.continuation_target,
        )
        if release is None or target is None:
            return
        if (
            not self.dry_run
            and transition.source.spotify_id not in self.destination_ids
        ):
            return
        if target.spotify_id in self.destination_ids:
            return
        if not self.dry_run:
            self.access.append(self.destination, target)
        self.destination_ids.add(target.spotify_id)
        self.presentation.continuation(release, target, self.dry_run)

    def _remove_source(self, source: PlaylistTrack) -> None:
        if not self.dry_run and source.spotify_id in self.destination_ids:
            self.access.remove(self.destination, source)
        self.destination_ids.discard(source.spotify_id)
        self.presentation.removed(source, self.dry_run)

    def _save_progress(self, transition: WineTransition) -> None:
        if self.dry_run:
            return
        self.progress.pop(transition.source.spotify_id, None)
        release, target = (
            transition.continuation_release,
            transition.continuation_target,
        )
        if release is not None and target is not None:
            self._track_progress(release, target, 0)
        elif transition.action == "advance" and transition.target is not None:
            streak = transition.plan.get(
                "next_prior_unliked_streak", transition.plan["consecutive_unliked"]
            )
            self._track_progress(transition.release, transition.target, streak)
        transition.entry["status"] = "completed"
        self.access.save(self.state)

    def _track_progress(
        self, release: ReleaseCandidate, target: ReleaseTrack, streak: object
    ) -> None:
        self.progress[target.spotify_id] = {
            "release": asdict(release),
            "prior_unliked_streak": streak,
            "updated_at": self.clock().isoformat(),
        }
