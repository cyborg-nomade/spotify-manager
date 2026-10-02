"""Prepare Queue 2's daily review after filling available New Kids capacity."""

from dataclasses import dataclass

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.discovery_queue import QueueTransferResult
from spotify_manager.application.discovery_run import active_review
from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_values import FillResult
from spotify_manager.application.new_kids_values import FlushSummary
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.new_kids_values import Queue2Summary
from spotify_manager.domain.catalog import PlaylistTrack


@dataclass(frozen=True)
class Queue2Snapshot:
    """Initial daily selection and complete remaining live queue after prefill.

    Args:
        selected: First marker for each eligible logical artist, up to the daily cap.
        remaining: Complete remaining queue, retaining unselected markers.
        prefill: Original New Kids transfer results.
        queue_length_before: Observed Queue 2 length before transfers.
        kids_length_before: Observed New Kids length before transfers.
        kids_length_after: New Kids length after accepted or projected transfers.
    """

    selected: list[PlaylistTrack]
    remaining: list[PlaylistTrack]
    prefill: tuple[FillResult, ...]
    queue_length_before: int
    kids_length_before: int
    kids_length_after: int


def prepare_queue_review(
    transfer: DiscoveryQueueTransfer, state: dict[str, object], daily_limit: int
) -> Queue2Snapshot:
    """Read both playlists before checking the original Queue 2 prefill conditions.

    Args:
        transfer: Original transfer service and live playlist observation boundary.
        state: Mutable namespace loaded before playlist reads.
        daily_limit: Original maximum unique logical artists reviewed per invocation.

    Returns:
        Daily selection, full remaining queue and original summary counts.

    Raises:
        NewKidsStateError: A real New Kids run blocks a fresh Queue 2 invocation.
    """
    current = list(transfer.access.playlist(transfer.destination))
    kids_before = len(current)
    queued = list(transfer.access.playlist(transfer.source))
    queue_before = len(queued)
    current, prefill, remaining = _prefill(transfer, state, current, queued)
    selected = _daily_selection(remaining, state, daily_limit)
    return Queue2Snapshot(
        selected, remaining, prefill, queue_before, kids_before, len(current)
    )


def _prefill(
    transfer: DiscoveryQueueTransfer,
    state: dict[str, object],
    current: list[PlaylistTrack],
    queued: list[PlaylistTrack],
) -> QueueTransferResult:
    run = state.get("queue_2_active_run")
    if (
        not transfer.dry_run
        and active_review(run)
        and isinstance(run, dict)
        and run.get("playlist_id") == transfer.source
    ):
        return current, (), queued
    if not transfer.dry_run and active_review(state.get("active_run")):
        raise NewKidsStateError(
            "The saved New Kids run must be resumed before Queue 2 can start."
        )
    return transfer.move(current, state, queued)


def _daily_selection(
    remaining: list[PlaylistTrack], state: dict[str, object], limit: int
) -> list[PlaylistTrack]:
    selected: list[PlaylistTrack] = []
    seen: set[str] = set()
    for marker in remaining:
        artist_id, _name = logical_artist(state, marker)
        if artist_id in seen:
            continue
        seen.add(artist_id)
        selected.append(marker)
        if len(selected) >= limit:
            break
    return selected


def queue_review_result(
    snapshot: Queue2Snapshot, review: FlushSummary, dry_run: bool
) -> Queue2Summary:
    """Retain the original Queue 2 public result after shared review completes.

    Args:
        snapshot: Accepted original queue observations and New Kids transfer results.
        review: Shared entry-review outcome, including its own resume determination.
        dry_run: Original invocation preview flag.

    Returns:
        Original Queue 2 summary using shared review's final queue length and status.
    """
    return Queue2Summary(
        results=review.results,
        prefill=snapshot.prefill,
        queue_length_before=snapshot.queue_length_before,
        queue_length_after=review.playlist_length_after,
        new_kids_length_before=snapshot.kids_length_before,
        new_kids_length_after=snapshot.kids_length_after,
        paused=review.paused,
        resumed=review.resumed,
        dry_run=dry_run,
    )
