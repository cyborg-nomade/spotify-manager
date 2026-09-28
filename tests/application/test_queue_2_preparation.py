"""Queue 2 prefill and daily selection retain their original observation boundaries."""

from dataclasses import replace

import pytest

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.new_kids_values import FillResult
from spotify_manager.application.new_kids_values import FlushSummary
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.queue_2 import prepare_queue_review
from spotify_manager.application.queue_2 import queue_review_result
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.discovery_effects import RunPlaylists
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))


def _transfer(
    memory: RunPlaylists, *, preview: bool = False, capacity: int = 10
) -> DiscoveryQueueTransfer:
    return DiscoveryQueueTransfer(
        memory, memory, memory, "kids", "queue", capacity, preview
    )


def _marker(index: int) -> PlaylistTrack:
    return replace(
        SOURCE, spotify_id=f"track-{index}", primary_artist_id=f"artist-{index}"
    )


def _names(memory: RunPlaylists) -> list[str]:
    return [name for name, value in memory.events]


def test_new_queue_run_fills_new_kids_before_selecting_remaining_markers() -> None:
    """Initial lengths precede transfers; review uses the untouched queue tail."""
    memory = RunPlaylists(reads={"kids": [()], "queue": [(SOURCE, _marker(1))]})
    snapshot = prepare_queue_review(_transfer(memory, capacity=1), {}, 10)
    assert snapshot.kids_length_before == 0 and snapshot.kids_length_after == 1
    assert snapshot.queue_length_before == 2
    assert snapshot.selected == snapshot.remaining == [_marker(1)]
    assert snapshot.prefill == (FillResult("Artist", SOURCE.name, "moved"),)
    assert memory.events[:2] == [("playlist", "kids"), ("playlist", "queue")]
    assert _names(memory) == [
        "playlist",
        "playlist",
        "append",
        "remove",
        "audit",
        "moved",
    ]


@pytest.mark.parametrize("status", ["active", "refilling"])
def test_resumed_queue_run_skips_prefill_and_defers_other_run_blocking(
    status: str,
) -> None:
    """Matching Queue 2 runs bypass prefill even if shared review will later block."""
    memory = RunPlaylists(reads={"kids": [()], "queue": [(SOURCE,)]})
    state: dict[str, object] = {
        "queue_2_active_run": {"status": status, "playlist_id": "queue"},
        "active_run": {"status": "active"},
    }
    snapshot = prepare_queue_review(_transfer(memory), state, 10)
    assert snapshot.selected == snapshot.remaining == [SOURCE]
    assert snapshot.prefill == () and snapshot.kids_length_after == 0
    assert _names(memory) == ["playlist", "playlist"]


@pytest.mark.parametrize(
    "run",
    [None, [], {"status": "done"}, {"status": "active", "playlist_id": "different"}],
)
def test_nonresumable_queue_records_still_prefill(run: object) -> None:
    """Absent, malformed, completed and other-playlist runs use fresh prefill rules."""
    memory = RunPlaylists(reads={"queue": [(SOURCE,)]})
    snapshot = prepare_queue_review(_transfer(memory), {"queue_2_active_run": run}, 10)
    assert snapshot.selected == snapshot.remaining == []
    assert snapshot.kids_length_after == 1 and snapshot.prefill[0].action == "moved"


@pytest.mark.parametrize("status", ["active", "refilling"])
def test_active_new_kids_blocks_after_both_live_playlist_reads(status: str) -> None:
    """Queue 2 preserves its later blocking boundary and original error text."""
    memory = RunPlaylists()
    with pytest.raises(NewKidsStateError, match="saved New Kids run must be resumed"):
        prepare_queue_review(_transfer(memory), {"active_run": {"status": status}}, 10)
    assert memory.events == [("playlist", "kids"), ("playlist", "queue")]


def test_preview_ignores_active_runs_and_excludes_projected_prefill_from_review() -> (
    None
):
    """Previews still transfer in memory instead of adopting saved queue snapshots."""
    memory = RunPlaylists(reads={"queue": [(SOURCE, _marker(1))]})
    state: dict[str, object] = {
        "active_run": {"status": "active"},
        "queue_2_active_run": {"status": "active", "playlist_id": "queue"},
    }
    snapshot = prepare_queue_review(
        _transfer(memory, preview=True, capacity=1), state, 10
    )
    assert snapshot.selected == [_marker(1)] and snapshot.kids_length_after == 1
    assert _names(memory) == ["playlist", "playlist", "audit", "moved"]
    assert state["active_run"] == {"status": "active"}


def test_daily_selection_keeps_first_marker_per_logical_artist_up_to_limit() -> None:
    """Duplicate markers remain live without consuming daily review slots."""
    queued = (SOURCE, SOURCE, _marker(1), _marker(2), _marker(3))
    memory = RunPlaylists(reads={"kids": [(_marker(99),)], "queue": [queued]})
    snapshot = prepare_queue_review(_transfer(memory, capacity=1), {}, 3)
    assert snapshot.selected == [SOURCE, _marker(1), _marker(2)]
    assert snapshot.remaining == list(queued)
    assert _names(memory) == ["playlist", "playlist"]


def test_daily_selection_uses_composer_route_credit() -> None:
    """A routed performer marker shares a daily slot with its logical composer."""
    duplicate = replace(_marker(1), primary_artist_id="composer")
    memory = RunPlaylists(
        reads={"kids": [(_marker(99),)], "queue": [(SOURCE, duplicate)]}
    )
    state: dict[str, object] = {
        "composer_routes": {
            "composer": {"artist_name": "Composer", "current_track_id": "source"}
        }
    }
    snapshot = prepare_queue_review(_transfer(memory, capacity=1), state, 10)
    assert snapshot.selected == [SOURCE] and snapshot.remaining == [SOURCE, duplicate]


def test_public_result_uses_shared_review_status_and_length() -> None:
    """Queue summary retains review's own paused/resumed flags and queue projection."""
    memory = RunPlaylists(reads={"queue": [(SOURCE, _marker(1))]})
    snapshot = prepare_queue_review(_transfer(memory, capacity=1), {}, 10)
    review = FlushSummary((), (), (), 9, 7, True, True, True)
    result = queue_review_result(snapshot, review, False)
    assert result.paused and result.resumed and not result.dry_run
    assert result.queue_length_before == 2 and result.queue_length_after == 7
    assert result.new_kids_length_before == 0 and result.new_kids_length_after == 1
    assert result.prefill == snapshot.prefill and result.results == review.results


def test_empty_queue_has_no_selection_or_prefill() -> None:
    """An empty observed queue produces an empty review without additional reads."""
    memory = RunPlaylists()
    snapshot = prepare_queue_review(_transfer(memory), {}, 10)
    assert snapshot.selected == snapshot.remaining == [] and snapshot.prefill == ()
    assert snapshot.queue_length_before == snapshot.kids_length_after == 0
    assert _names(memory) == ["playlist", "playlist"]
