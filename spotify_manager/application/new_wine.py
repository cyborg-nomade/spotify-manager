"""Coordinate New Wine planning, ordered execution and resumable cellar refill."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import cast

from spotify_manager.application.new_wine_execution import WineExecution
from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.new_wine_planner import WinePlanner
from spotify_manager.application.new_wine_state import source_from_record
from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import EndpointChoiceReader
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.new_wine_values import FlushSummary
from spotify_manager.application.new_wine_values import NewWineConfigError
from spotify_manager.application.new_wine_values import NewWineStateError
from spotify_manager.application.new_wine_values import ReleaseChoiceReader
from spotify_manager.application.ports.new_wine import NewWineAccess
from spotify_manager.application.ports.new_wine import NewWinePresentation
from spotify_manager.domain.catalog import PlaylistTrack


@dataclass(frozen=True)
class NewWineOptions:
    """Configured destinations and original invocation modes.

    Args:
        destination: New Wine playlist identifier.
        sauvignon: Sauvignon destination identifier.
        cellar: Optional refill source.
        no_discovery: Whether refill requires existing library affinity.
        endpoint_mode: Whether album/EP endpoint prompts are requested.
        dry_run: Whether remote effects and checkpoints are suppressed.
    """

    destination: str
    sauvignon: str
    cellar: str | None
    no_discovery: bool
    endpoint_mode: bool
    dry_run: bool


@dataclass(frozen=True)
class NewWineDependencies:
    """Explicit observation, interaction and effect boundaries for one invocation.

    Args:
        access: Playlist, library, namespace, audit and refill integrations.
        observations: Fresh per-run catalog and liked-status cache.
        choose: Original release selection callback.
        endpoint: Optional original endpoint selection callback.
        presentation: Original planning and effect messages.
        clock: Original UTC clock for run and progress timestamps.
        progress: Optional progress/cancellation callback.
    """

    access: NewWineAccess
    observations: WineObservations
    choose: ReleaseChoiceReader
    endpoint: EndpointChoiceReader | None
    presentation: NewWinePresentation
    clock: Callable[[], datetime]
    progress: Callable[[int, int, str], None] | None = None


def flush_new_wine(
    options: NewWineOptions, dependencies: NewWineDependencies
) -> FlushSummary:
    """Advance every original marker once, then refill available cellar slots.

    Args:
        options: Existing destinations and invocation modes.
        dependencies: Run-owned integrations and operator callbacks.

    Returns:
        Original summary including pause, resume and optional refill results.

    Raises:
        NewWineStateError: Durable records cannot be reconstructed safely.
        NewWineConfigError: Endpoint mode has no endpoint choice reader.
        NewWineError: Live observations or operator selections are invalid.
    """
    tracks = dependencies.access.playlist(options.destination)
    ids = {track.spotify_id for track in tracks}
    sauvignon = dependencies.access.playlist(options.sauvignon)
    sauvignon_ids = {track.spotify_id for track in sauvignon}
    state = dependencies.access.load_state(options.dry_run)
    run, resumed = _select_run(options, dependencies, state, tracks)
    run_id = str(run["run_id"])
    entries, progress = _records(run, state)
    endpoint_mode = bool(run.get("choose_album_endpoints", options.endpoint_mode))
    if endpoint_mode and dependencies.endpoint is None:
        raise NewWineConfigError(
            "Album endpoint selection requires an endpoint choice reader."
        )
    execution = WineExecution(
        dependencies.access,
        dependencies.observations,
        options.destination,
        options.sauvignon,
        ids,
        sauvignon_ids,
        state,
        progress,
        options.dry_run,
        dependencies.presentation,
        dependencies.clock,
    )
    planner = WinePlanner(
        dependencies.observations,
        progress,
        dependencies.choose,
        dependencies.endpoint,
        endpoint_mode,
        options.dry_run,
        execution.checkpoint,
        dependencies.presentation,
    )
    return NewWineRun(
        options, dependencies, execution, planner, state, run, run_id, entries, resumed
    ).execute()


def _select_run(
    options: NewWineOptions,
    dependencies: NewWineDependencies,
    state: dict[str, object],
    tracks: tuple[PlaylistTrack, ...],
) -> tuple[dict[str, object], bool]:
    active = state.get("active_run")
    if not options.dry_run and _resumable(active, options.destination):
        return cast(dict[str, object], active), True
    run = new_run(options, tracks, dependencies.clock)
    if not options.dry_run:
        state["active_run"] = run
        dependencies.access.save(state)
    return run, False


def _resumable(raw: object, playlist_id: str) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("status") == "active"
        and raw.get("playlist_id") == playlist_id
    )


def new_run(
    options: NewWineOptions,
    tracks: tuple[PlaylistTrack, ...],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Snapshot original markers with the existing run layout and clock boundaries.

    Args:
        options: Existing destinations and invocation modes.
        tracks: Original ordered playlist observations.
        clock: Timestamp source read separately for identifier and creation time.

    Returns:
        Original active-run record with no pending refill transfer.
    """
    return {
        "run_id": clock().strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": options.destination,
        "wine_cellar_playlist_id": options.cellar,
        "no_discovery": options.no_discovery,
        "choose_album_endpoints": options.endpoint_mode,
        "status": "active",
        "created_at": clock().isoformat(),
        "entries": _snapshot(tracks),
        "refill_pending": None,
    }


def _snapshot(tracks: tuple[PlaylistTrack, ...]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for track in tracks:
        entries.append(
            {
                "source": asdict(track),
                "status": "pending",
                "plan": None,
                "endpoint_choice": None,
            }
        )
    return entries


def _records(
    run: dict[str, object], state: dict[str, object]
) -> tuple[list[object], dict[str, object]]:
    entries = run.get("entries")
    if not isinstance(entries, list):
        raise NewWineStateError("New Wine run contains invalid entries.")
    progress = state.get("track_progress")
    if not isinstance(progress, dict):
        raise NewWineStateError("New Wine track progress is invalid.")
    return entries, cast(dict[str, object], progress)


def _entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise NewWineStateError("New Wine run contains an invalid entry.")
    return cast(dict[str, object], raw)


def _finished(entries: list[object]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") not in {
            "completed",
            "skipped",
        }:
            return False
    return True


@dataclass
class NewWineRun:
    """Own one run's entry processing, summary and post-flush completion boundary.

    Args:
        options: Original invocation settings.
        dependencies: Explicit outer integrations and callbacks.
        execution: Ordered effect executor and membership projections.
        planner: Operator choices and observation policy.
        state: Complete mutable namespace.
        run: Current durable run.
        run_id: Original coerced execution identifier.
        entries: Original entry sequence, validated as each entry is reached.
        resumed: Whether an existing active run was selected.
        results: Results produced in this invocation.
        paused: Whether the operator requested a pause.
    """

    options: NewWineOptions
    dependencies: NewWineDependencies
    execution: WineExecution
    planner: WinePlanner
    state: dict[str, object]
    run: dict[str, object]
    run_id: str
    entries: list[object]
    resumed: bool
    results: list[FlushResult] = field(default_factory=list)
    paused: bool = False

    def execute(self) -> FlushSummary:
        """Process entries, then refill and mark completion at the original boundaries.

        Returns:
            Original summary of this invocation's outcomes.
        """
        for index, raw in enumerate(self.entries, start=1):
            if not self._review(_entry(raw), index):
                self.paused = True
                break
        refill = self._refill()
        self._finish()
        return self._summary(refill)

    def _review(self, entry: dict[str, object], index: int) -> bool:
        if entry.get("status") in {"completed", "skipped"}:
            return True
        source = source_from_record(entry.get("source"))
        self._progress(index - 1, f"{source.primary_artist_name} - {source.name}")
        raw = entry.get("plan")
        plan = cast(dict[str, object], raw) if isinstance(raw, dict) else None
        if plan is None:
            decision = self.planner.plan(source, entry)
            if not isinstance(decision, dict):
                return self._skip_or_pause(entry, decision)
            plan = decision
            entry["plan"] = plan
            self.execution.checkpoint()
        result = self.execution.execute(source, entry, plan)
        self._record(result)
        self._progress(index, f"Completed {source.name}")
        return True

    def _skip_or_pause(
        self, entry: dict[str, object], result: FlushResult | None
    ) -> bool:
        if result is None:
            return False
        entry["status"] = "skipped"
        self._record(result)
        self.execution.checkpoint()
        return True

    def _record(self, result: FlushResult) -> None:
        self.results.append(result)
        self.dependencies.access.audit(self.run_id, result)

    def _progress(self, completed: int, label: str) -> None:
        if self.dependencies.progress is not None:
            self.dependencies.progress(completed, len(self.entries), label)

    def _refill(self) -> CellarRefillSummary | None:
        cellar = self.run.get("wine_cellar_playlist_id")
        if not isinstance(cellar, str) or not cellar:
            cellar = self.options.cellar
        no_discovery = (
            bool(self.run["no_discovery"])
            if "no_discovery" in self.run
            else self.options.no_discovery
        )
        if self.paused or not cellar:
            return None
        assert isinstance(cellar, str)
        projected = (
            set(self.execution.destination_ids) if self.options.dry_run else None
        )
        return self.dependencies.access.refill(
            cellar, no_discovery, self.options.dry_run, self.state, self.run, projected
        )

    def _finish(self) -> None:
        if self.options.dry_run or self.paused or not _finished(self.entries):
            return
        self.run["status"] = "completed"
        self.run["completed_at"] = self.dependencies.clock().isoformat()
        self.dependencies.access.save(self.state)

    def _summary(self, refill: CellarRefillSummary | None) -> FlushSummary:
        return FlushSummary(
            run_id=self.run_id,
            total=len(self.entries),
            processed=len(self.results),
            advanced=sum(result.action == "advance" for result in self.results),
            dropped=sum(result.action == "drop" for result in self.results),
            sent_to_sauvignon=sum(
                result.action == "sauvignon" for result in self.results
            ),
            completed_singles=sum(
                result.action == "complete single" for result in self.results
            ),
            skipped=sum(result.action == "skip" for result in self.results),
            albums_unsaved=sum(result.album_unsaved for result in self.results),
            paused=self.paused,
            dry_run=self.options.dry_run,
            resumed=self.resumed,
            results=tuple(self.results),
            refill=refill,
        )
