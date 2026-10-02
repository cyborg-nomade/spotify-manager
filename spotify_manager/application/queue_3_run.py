"""Prepare, acknowledge and finish Queue 3 runs using the original restart rules."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.queue_3_execution import Queue3LiveQueue
from spotify_manager.application.queue_3_state import new_run
from spotify_manager.application.queue_3_values import AnnualImportResult
from spotify_manager.application.queue_3_values import FlushResult
from spotify_manager.application.queue_3_values import FlushSummary
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.domain.catalog import ReleaseTrack


@dataclass(frozen=True)
class Queue3Snapshot:
    """Validated mutable run containers and the original public run identifier.

    Args:
        record: Complete active run record.
        identifier: Original string-coerced run ID.
        entries: Ordered original entry records, validated individually during review.
        orders: Shared durable release-order preferences.
        routes: Shared durable logical-composer routes.
        resumed: Whether this run was accepted from saved state.
    """

    record: dict[str, object]
    identifier: str
    entries: list[object]
    orders: dict[str, object]
    routes: dict[str, object]
    resumed: bool


@dataclass(frozen=True)
class Queue3Run:
    """Own namespace checkpoints without altering original preview or resume behavior.

    Args:
        state: Caller-prepared namespace, already cloned for a preview.
        access: Original namespace persistence boundary.
        clock: Original UTC clock for run identity and accepted acknowledgment times.
        dry_run: Whether durable writes and acknowledgments are suppressed.
        limit: Original daily logical-artist cap.
    """

    state: dict[str, object]
    access: RoutineState
    clock: Callable[[], datetime]
    dry_run: bool
    limit: int = 10

    def start(self, queue: Queue3LiveQueue) -> Queue3Snapshot:
        """Resume a matching active run or snapshot and checkpoint current markers.

        Args:
            queue: Already observed destination and annual-import projections.

        Returns:
            Validated mutable run containers and original resume status.

        Raises:
            Queue3StateError: Entries, release orders or composer routes are malformed.
            KeyError: Required source, route or run fields are missing.
            OSError: The initial checkpoint fails after working state is updated.
        """
        active = self.state.get("active_run")
        resumed = (
            not self.dry_run
            and isinstance(active, dict)
            and active.get("status") == "active"
            and active.get("playlist_id") == queue.playlist_id
        )
        record = cast(dict[str, object], active) if resumed else self._new(queue)
        return _snapshot(record, self.state, resumed)

    def save(self) -> None:
        """Checkpoint the complete namespace only for real execution.

        Raises:
            OSError: The original namespace store rejects the checkpoint.
        """
        if not self.dry_run:
            self.access.save(self.state)

    def timestamp(self) -> str:
        """Read the original route or completion timestamp.

        Returns:
            Original UTC clock value serialized with ISO formatting.
        """
        return self.clock().isoformat()

    def acknowledge(
        self,
        entry: dict[str, object],
        action: str,
        target: ReleaseTrack | None,
        artist_id: str,
        routes: dict[str, object],
    ) -> None:
        """Update route and entry status only after the transition audit succeeds.

        Args:
            entry: Original mutable durable entry.
            action: Accepted execution action.
            target: Original decoded replacement, when present.
            artist_id: Logical artist whose composer route may advance.
            routes: Already validated shared composer routes.

        Raises:
            OSError: Checkpoint fails after the working acknowledgment is applied.
        """
        if self.dry_run:
            return
        if action == "composer_advance" and target is not None:
            self._advance_route(routes.get(artist_id), target)
        entry["status"] = "skipped" if action == "skip" else "completed"
        self.save()

    def finish(self, snapshot: Queue3Snapshot, paused: bool) -> None:
        """Checkpoint overall completion only when every real entry is acknowledged.

        Args:
            snapshot: Original accepted run containers.
            paused: Whether the operator paused before a plan was accepted.

        Raises:
            OSError: Completion checkpoint fails after working completion is applied.
        """
        if self.dry_run or paused or not _all_finished(snapshot.entries):
            return
        snapshot.record["status"] = "completed"
        snapshot.record["completed_at"] = self.timestamp()
        self.save()

    def _new(self, queue: Queue3LiveQueue) -> dict[str, object]:
        record = new_run(
            queue.playlist_id, queue.tracks, self.state, self.clock, self.limit
        )
        if not self.dry_run:
            self.state["active_run"] = record
            self.save()
        return record

    def _advance_route(self, route: object, target: ReleaseTrack) -> None:
        if not isinstance(route, dict):
            return
        route["current_track_id"] = target.spotify_id
        route["updated_at"] = self.timestamp()


def _snapshot(
    record: dict[str, object],
    state: dict[str, object],
    resumed: bool,
) -> Queue3Snapshot:
    entries = record.get("entries")
    if not isinstance(entries, list):
        raise Queue3StateError("Queue 3 active run has invalid entries.")
    orders = state.get("release_orders")
    if not isinstance(orders, dict):
        raise Queue3StateError("Queue 3 release-order state is invalid.")
    routes = state.get("composer_routes")
    if not isinstance(routes, dict):
        raise Queue3StateError("Queue 3 composer-route state is invalid.")
    return Queue3Snapshot(
        record, str(record["run_id"]), entries, orders, routes, resumed
    )


def _all_finished(entries: list[object]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") not in {
            "completed",
            "skipped",
        }:
            return False
    return True


def run_summary(
    snapshot: Queue3Snapshot,
    results: tuple[FlushResult, ...],
    annual: tuple[AnnualImportResult, ...],
    paused: bool,
    dry_run: bool,
) -> FlushSummary:
    """Count new public actions separately from previously acknowledged entries.

    Args:
        snapshot: Original run metadata and complete entry sequence.
        results: Transitions processed in this invocation.
        annual: Annual import decisions preceding this review.
        paused: Whether this invocation paused for an operator decision.
        dry_run: Whether this was a preview.

    Returns:
        Original Queue 3 public summary with unchanged action categories.
    """
    return FlushSummary(
        run_id=snapshot.identifier,
        total=len(snapshot.entries),
        processed=len(results),
        advanced=sum(
            result.action in {"advance", "composer playlist"} for result in results
        ),
        changed_releases=sum(result.action == "next release" for result in results),
        completed_artists=sum(result.action == "complete" for result in results),
        skipped=sum(result.action == "skip" for result in results),
        annual_import=annual,
        paused=paused,
        dry_run=dry_run,
        resumed=snapshot.resumed,
        results=results,
    )
