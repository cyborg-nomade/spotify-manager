"""Execute Slow Listening choices and checkpoints in their established order."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from functools import partial
from typing import cast

from spotify_manager.application.ports.slow_listening import SlowListeningAccess
from spotify_manager.application.ports.slow_listening import SlowListeningPresentation
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.application.slow_listening_plan import StudioObservations
from spotify_manager.application.slow_listening_plan import TrackSelection
from spotify_manager.application.slow_listening_state import release_from_record
from spotify_manager.application.slow_listening_state import result_from_plan
from spotify_manager.application.slow_listening_state import snapshot_entries
from spotify_manager.application.slow_listening_state import source_from_record
from spotify_manager.application.slow_listening_state import track_from_record
from spotify_manager.application.slow_listening_values import CompletionNotifier
from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.application.slow_listening_values import FlushSummary
from spotify_manager.application.slow_listening_values import ReleaseOrderReader
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from spotify_manager.application.slow_listening_values import TrackActionReader
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


@dataclass(frozen=True)
class SlowListeningDependencies:
    """Explicit integrations and interaction callbacks for one routine invocation.

    Args:
        access: Playlist, namespace and audit boundary.
        observations: Run-scoped catalog cache.
        order: Operator's release-order choice callback.
        choose: Operator's track choice callback.
        complete: Completion acknowledgement callback, which may edit the playlist.
        presentation: Existing output messages.
        clock: Clock read at the original run creation and completion boundaries.
        progress: Optional cancellation/progress callback.
    """

    access: SlowListeningAccess
    observations: StudioObservations
    order: ReleaseOrderReader
    choose: TrackActionReader
    complete: CompletionNotifier
    presentation: SlowListeningPresentation
    clock: Callable[[], datetime]
    progress: Callable[[int, int, str], None] | None = None


def new_run(
    playlist_id: str, tracks: tuple[PlaylistTrack, ...], clock: Callable[[], datetime]
) -> dict[str, object]:
    """Create the unchanged durable run layout with two distinct clock reads.

    Args:
        playlist_id: Playlist whose first two markers are selected.
        tracks: Initial live observations.
        clock: Original UTC clock callback.

    Returns:
        Active run with original timestamps and pending entries.
    """
    return {
        "run_id": clock().strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "created_at": clock().isoformat(),
        "entries": snapshot_entries(tracks),
    }


def flush_slow_listening(
    playlist_id: str, dependencies: SlowListeningDependencies, *, dry_run: bool = False
) -> FlushSummary:
    """Advance at most two saved markers, retaining accepted effects on failure.

    Args:
        playlist_id: Configured Slow Listening playlist identifier.
        dependencies: Run-owned integrations and interaction callbacks.
        dry_run: Preview using fresh state while retaining the legacy audit writes.

    Returns:
        Original summary, including resume and pause status.

    Raises:
        SlowListeningStateError: Durable records or resumed live membership are invalid.
        SlowListeningError: Catalog observations or operator choices are invalid.
    """
    tracks = dependencies.access.playlist()
    state = dependencies.access.load_state(dry_run)
    run, resumed = _select_run(playlist_id, tracks, dependencies, state, dry_run)
    entries = _entries(run)
    orders = _orders(state)
    session = SlowListeningRun(
        dependencies,
        state,
        run,
        entries,
        orders,
        dry_run,
        resumed,
        {track.spotify_id for track in tracks},
    )
    return session.execute()


def _select_run(
    playlist_id: str,
    tracks: tuple[PlaylistTrack, ...],
    dependencies: SlowListeningDependencies,
    state: dict[str, object],
    dry_run: bool,
) -> tuple[dict[str, object], bool]:
    active = state.get("active_run")
    if not dry_run and _resumable(active, playlist_id):
        return cast(dict[str, object], active), True
    run = new_run(playlist_id, tracks, dependencies.clock)
    if not dry_run:
        state["active_run"] = run
        dependencies.access.save(state)
    return run, False


def _resumable(raw: object, playlist_id: str) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("status") == "active"
        and raw.get("playlist_id") == playlist_id
    )


def _entries(run: dict[str, object]) -> list[object]:
    entries = run.get("entries")
    if not isinstance(entries, list):
        raise SlowListeningStateError("Slow Listening run has invalid entries.")
    return entries


def _orders(state: dict[str, object]) -> dict[str, object]:
    orders = state.get("release_orders")
    if not isinstance(orders, dict):
        raise SlowListeningStateError("Slow Listening release orders are invalid.")
    return cast(dict[str, object], orders)


def _entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening run has an invalid entry.")
    return cast(dict[str, object], raw)


def _skipped_ids(entry: dict[str, object]) -> list[str]:
    raw = entry.setdefault("skipped_candidates", [])
    if not isinstance(raw, list) or not all(
        isinstance(candidate, str) for candidate in raw
    ):
        raise SlowListeningStateError(
            "Slow Listening run has invalid skipped candidates."
        )
    return cast(list[str], raw)


def _finished(entries: list[object]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") not in {
            "completed",
            "skipped",
        }:
            return False
    return True


@dataclass
class SlowListeningRun:
    """Own one resumable run's state, observations and ordered effects.

    Args:
        dependencies: Explicit integrations and operator callbacks.
        state: Complete mutable namespace loaded for this invocation.
        run: Active run retained inside the namespace for real execution.
        entries: Original entry sequence, validated as each entry is reached.
        orders: Mutable saved release tie choices.
        dry_run: Whether remote mutations and checkpoints are omitted.
        resumed: Whether an existing active run was selected.
        live_ids: Current observed membership, updated after each accepted effect.
        results: Results produced in this invocation.
        paused: Whether the operator requested a pause.
    """

    dependencies: SlowListeningDependencies
    state: dict[str, object]
    run: dict[str, object]
    entries: list[object]
    orders: dict[str, object]
    dry_run: bool
    resumed: bool
    live_ids: set[str]
    results: list[FlushResult] = field(default_factory=list)
    paused: bool = False

    def execute(self) -> FlushSummary:
        """Process pending entries, then mark the run complete when appropriate.

        Returns:
            Public summary of only the transitions performed by this invocation.
        """
        run_id = str(self.run["run_id"])
        for index, raw in enumerate(self.entries, start=1):
            if not self._review(_entry(raw), index, run_id):
                self.paused = True
                break
        self._finish()
        return self._summary(run_id)

    def _review(self, entry: dict[str, object], index: int, run_id: str) -> bool:
        if entry.get("status") in {"completed", "skipped"}:
            return True
        source = source_from_record(entry.get("source"))
        self._progress(index - 1, f"{source.primary_artist_name} - {source.name}")
        plan = self._plan(entry, source)
        if plan is None:
            return False
        self._save_plan(entry, plan)
        action = str(plan["action"])
        target = track_from_record(plan.get("target"))
        release = release_from_record(plan.get("target_release"))
        if action == "skip":
            self._skip(entry, source, plan, run_id)
            return True
        self._transition(source, action, target, release)
        self._acknowledge(source, action, plan)
        self._record(source, plan, run_id)
        self._mark(entry, "completed")
        self._progress(index, f"Completed {source.name}")
        return True

    def _plan(
        self, entry: dict[str, object], source: PlaylistTrack
    ) -> dict[str, object] | None:
        raw = entry.get("plan")
        if isinstance(raw, dict):
            return cast(dict[str, object], raw)
        skipped = _skipped_ids(entry)
        observations = self.dependencies.observations
        catalog = observations.discography(source.primary_artist_id)
        ordering = ReleaseOrdering(self.dependencies.order, self.orders, self._save)
        selection = TrackSelection(
            source,
            catalog,
            observations,
            ordering,
            self.dependencies.choose,
            set(skipped),
            partial(self._persist_skip, skipped),
        )
        return selection.plan()

    def _save(self) -> None:
        if not self.dry_run:
            self.dependencies.access.save(self.state)

    def _persist_skip(self, skipped: list[str], spotify_id: str) -> None:
        skipped.append(spotify_id)
        self._save()

    def _save_plan(self, entry: dict[str, object], plan: dict[str, object]) -> None:
        if entry.get("plan") is None:
            entry["plan"] = plan
            self._save()

    def _mark(self, entry: dict[str, object], status: str) -> None:
        if not self.dry_run:
            entry["status"] = status
            self._save()

    def _skip(
        self,
        entry: dict[str, object],
        source: PlaylistTrack,
        plan: dict[str, object],
        run_id: str,
    ) -> None:
        result = self._record(source, plan, run_id)
        self.dependencies.presentation.skipped(source, result)
        self._mark(entry, "skipped")

    def _record(
        self, source: PlaylistTrack, plan: dict[str, object], run_id: str
    ) -> FlushResult:
        result = result_from_plan(source, plan, dry_run=self.dry_run)
        self.results.append(result)
        self.dependencies.access.audit(run_id, result)
        return result

    def _transition(
        self,
        source: PlaylistTrack,
        action: str,
        target: ReleaseTrack | None,
        release: DiscographyRelease | None,
    ) -> None:
        if source.spotify_id not in self.live_ids:
            self._resume(source, action, target)
            return
        if action == "advance" and target is not None:
            self._advance(source, target, release)
            return
        if action == "complete":
            self._remove(source)
            self.dependencies.presentation.completed(source, self.dry_run)

    def _resume(
        self, source: PlaylistTrack, action: str, target: ReleaseTrack | None
    ) -> None:
        if (
            action == "advance"
            and target is not None
            and target.spotify_id not in self.live_ids
        ):
            raise SlowListeningStateError(
                f"{source.name} is absent but its planned replacement "
                f"{target.name} is not in Slow Listening."
            )
        self.dependencies.presentation.resumed(source)

    def _advance(
        self,
        source: PlaylistTrack,
        target: ReleaseTrack,
        release: DiscographyRelease | None,
    ) -> None:
        if target.spotify_id not in self.live_ids:
            self._append(target, release)
        self._remove(source)
        self.dependencies.presentation.removed(source, self.dry_run)

    def _append(self, target: ReleaseTrack, release: DiscographyRelease | None) -> None:
        if not self.dry_run:
            self.dependencies.access.append(target)
        self.live_ids.add(target.spotify_id)
        self.dependencies.presentation.added(
            target, release.name if release else "?", self.dry_run
        )

    def _remove(self, source: PlaylistTrack) -> None:
        if not self.dry_run:
            self.dependencies.access.remove(source)
        self.live_ids.discard(source.spotify_id)

    def _acknowledge(
        self, source: PlaylistTrack, action: str, plan: dict[str, object]
    ) -> None:
        if (
            self.dry_run
            or action != "complete"
            or bool(plan.get("completion_acknowledged"))
        ):
            return
        self.dependencies.complete(source)
        plan["completion_acknowledged"] = True
        self._save()
        tracks = self.dependencies.access.playlist()
        self.live_ids = {track.spotify_id for track in tracks}

    def _progress(self, completed: int, label: str) -> None:
        if self.dependencies.progress is not None:
            self.dependencies.progress(completed, len(self.entries), label)

    def _finish(self) -> None:
        if self.dry_run or self.paused or not _finished(self.entries):
            return
        self.run["status"] = "completed"
        self.run["completed_at"] = self.dependencies.clock().isoformat()
        self._save()

    def _summary(self, run_id: str) -> FlushSummary:
        return FlushSummary(
            run_id=run_id,
            total=len(self.entries),
            processed=len(self.results),
            advanced=sum(result.action == "advance" for result in self.results),
            completed_artists=sum(
                result.action == "complete" for result in self.results
            ),
            skipped=sum(result.action == "skip" for result in self.results),
            paused=self.paused,
            dry_run=self.dry_run,
            resumed=self.resumed,
            results=tuple(self.results),
        )
