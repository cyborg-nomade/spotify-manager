"""Prepare and finalize restart-safe New Kids and Queue 2 review snapshots."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.new_kids_state import new_run
from spotify_manager.application.new_kids_values import FillResult
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import FlushSummary
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack


@dataclass(frozen=True)
class ReviewSnapshot:
    """Accepted run and live membership for one review invocation.

    Args:
        run: Mutable original active run.
        entries: Validated snapshot entry sequence, retaining malformed entries.
        live_ids: Mutable observed/projected review playlist membership.
        length_before: Original prefill playlist length.
        prefill: Accepted initial queue transfer results.
        resumed: Whether an existing active/refilling run was accepted.
    """

    run: dict[str, object]
    entries: list[object]
    live_ids: set[str]
    length_before: int
    prefill: tuple[FillResult, ...]
    resumed: bool


def active_review(raw: object) -> bool:
    """Recognize the original active and refilling run statuses.

    Args:
        raw: Tolerantly decoded optional run record.

    Returns:
        Whether an existing record has an active or refilling status.
    """
    return isinstance(raw, dict) and raw.get("status") in {"active", "refilling"}


@dataclass(frozen=True)
class DiscoveryRun:
    """Own snapshot, resume and refill checkpoints over existing state and playlists.

    Args:
        state_access: Existing namespace checkpoint boundary.
        transfer: Queue transfer service, also supplying original playlist reads.
        state: Mutable complete namespace.
        playlist_id: Review playlist identifier.
        active_key: Original active-run namespace key.
        blocking_key: Other review's run key that blocks real execution.
        fill_from_queue: Whether this review performs initial and final queue transfers.
        dry_run: Whether to suppress namespace and remote writes.
        clock: Original UTC clock for run identifiers and timestamps.
    """

    state_access: RoutineState
    transfer: DiscoveryQueueTransfer
    state: dict[str, object]
    playlist_id: str
    active_key: str
    blocking_key: str
    fill_from_queue: bool
    dry_run: bool
    clock: Callable[[], datetime]

    def prepare(
        self,
        initial: list[PlaylistTrack] | None = None,
        live: list[PlaylistTrack] | None = None,
    ) -> ReviewSnapshot:
        """Accept a resumable snapshot or create one after the original prefill.

        Args:
            initial: Optional supplied initial selection for a new run.
            live: Optional supplied live sequence, used for resume and execution.

        Returns:
            Original accepted snapshot with a fresh live membership projection.

        Raises:
            NewKidsStateError: Another run blocks execution or entries are malformed.
        """
        self._check_blocking()
        raw = self.state.get(self.active_key)
        resumed = bool(
            not self.dry_run
            and active_review(raw)
            and isinstance(raw, dict)
            and raw.get("playlist_id") == self.playlist_id
        )
        if resumed:
            run = cast(dict[str, object], raw)
            length_before = len(self._tracks(live))
            prefill: tuple[FillResult, ...] = ()
        else:
            run, length_before, prefill = self._start(initial)
        entries = run.get("entries")
        if not isinstance(entries, list):
            raise NewKidsStateError("New Kids active run has invalid entries.")
        live_ids = {track.spotify_id for track in self._tracks(live)}
        return ReviewSnapshot(run, entries, live_ids, length_before, prefill, resumed)

    def finish(
        self, snapshot: ReviewSnapshot, results: tuple[FlushResult, ...], paused: bool
    ) -> FlushSummary:
        """Refill completed runs and clear their active record at original checkpoints.

        Args:
            snapshot: Accepted snapshot and projected live memberships.
            results: Completed/skipped public entry results in source order.
            paused: Whether interaction stopped review before completion.

        Returns:
            Original public summary using the original preview refresh behavior.
        """
        length_after = len(snapshot.live_ids)
        postfill: tuple[FillResult, ...] = ()
        if not paused:
            if self.fill_from_queue:
                length_after, postfill = self._refill(snapshot.run)
            self._clear()
        return FlushSummary(
            results,
            snapshot.prefill,
            postfill,
            snapshot.length_before,
            length_after,
            paused,
            snapshot.resumed,
            self.dry_run,
        )

    def _check_blocking(self) -> None:
        if self.dry_run or not active_review(self.state.get(self.blocking_key)):
            return
        raise NewKidsStateError(
            f"A saved {self.blocking_key.replace('_', ' ')} must be "
            "resumed before starting this run."
        )

    def _tracks(self, supplied: list[PlaylistTrack] | None) -> list[PlaylistTrack]:
        if supplied is not None:
            return list(supplied)
        return list(self.transfer.access.playlist(self.playlist_id))

    def _start(
        self, initial: list[PlaylistTrack] | None
    ) -> tuple[dict[str, object], int, tuple[FillResult, ...]]:
        current = self._tracks(initial)
        length_before = len(current)
        prefill: tuple[FillResult, ...] = ()
        if self.fill_from_queue:
            current, prefill, _remaining = self.transfer.move(current, self.state)
        run = new_run(self.playlist_id, current, self.state, self.clock)
        if not self.dry_run:
            self.state[self.active_key] = run
            self.state_access.save(self.state)
        return run, length_before, prefill

    def _refill(self, run: dict[str, object]) -> tuple[int, tuple[FillResult, ...]]:
        if not self.dry_run:
            run["status"] = "refilling"
            self.state_access.save(self.state)
        current = self._tracks(None)
        current, results, _remaining = self.transfer.move(current, self.state)
        return len(current), results

    def _clear(self) -> None:
        if not self.dry_run:
            self.state[self.active_key] = None
            self.state_access.save(self.state)
