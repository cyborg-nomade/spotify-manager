"""Review run lifecycle preserves snapshot, resume, refill and checkpoint ordering."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.discovery_run import DiscoveryRun
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.discovery_effects import MemoryEffects
from tests.support.discovery_effects import MemoryQueue
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))


@dataclass
class RunPlaylists(MemoryQueue):
    """Return per-playlist observations in original request order.

    Args:
        reads: Ordered responses for each requested playlist.
    """

    reads: dict[str, list[tuple[PlaylistTrack, ...]]] = field(default_factory=dict)

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Consume one scripted live response, defaulting to an empty playlist.

        Args:
            playlist_id: Review or queue playlist identifier.

        Returns:
            Next ordered live response for this playlist.
        """
        self._record("playlist", playlist_id)
        responses = self.reads.get(playlist_id, [])
        return responses.pop(0) if responses else ()


def _case(
    *, preview: bool = False, fill: bool = True
) -> tuple[DiscoveryRun, MemoryEffects, RunPlaylists]:
    effects = MemoryEffects()
    playlists = RunPlaylists(events=effects.events)
    transfer = DiscoveryQueueTransfer(
        playlists, playlists, playlists, "kids", "queue", 10, preview
    )
    state: dict[str, object] = {"artists": {}, "composer_routes": {}}
    lifecycle = DiscoveryRun(
        effects,
        transfer,
        state,
        "kids",
        "active_run",
        "queue_2_active_run",
        fill,
        preview,
        effects.clock,
    )
    return lifecycle, effects, playlists


def _saved(status: str = "active", playlist: str = "kids") -> dict[str, object]:
    return {
        "status": status,
        "playlist_id": playlist,
        "entries": [{"source": asdict(SOURCE)}],
    }


def _names(effects: MemoryEffects) -> list[str]:
    return [name for name, value in effects.events]


def test_new_run_prefills_then_snapshots_before_a_second_live_read() -> None:
    """A fresh snapshot contains transfers while its length-before precedes prefill."""
    lifecycle, effects, playlists = _case()
    playlists.reads = {"kids": [(), (SOURCE,)], "queue": [(SOURCE,)]}
    snapshot = lifecycle.prepare()
    assert snapshot.length_before == 0 and not snapshot.resumed
    assert snapshot.live_ids == {"source"} and snapshot.prefill[0].action == "moved"
    assert snapshot.entries[0] == {
        "source": asdict(SOURCE),
        "artist_id": "artist",
        "artist_name": "Artist",
        "status": "pending",
        "plan": None,
    }
    assert _names(effects) == [
        "playlist",
        "playlist",
        "append",
        "remove",
        "audit",
        "moved",
        "checkpoint",
        "playlist",
    ]
    assert lifecycle.state["active_run"] is snapshot.run
    assert effects.clock_reads == 2


@pytest.mark.parametrize("status", ["active", "refilling"])
def test_resume_uses_saved_entries_and_skips_prefill(status: str) -> None:
    """Both active and refilling snapshots resume without creating another run."""
    lifecycle, effects, playlists = _case()
    saved = _saved(status)
    lifecycle.state["active_run"] = saved
    playlists.reads["kids"] = [(SOURCE,), ()]
    snapshot = lifecycle.prepare(initial=[])
    assert snapshot.resumed and snapshot.run is saved
    assert snapshot.length_before == 1 and snapshot.live_ids == set()
    assert snapshot.prefill == () and _names(effects) == ["playlist", "playlist"]
    assert effects.clock_reads == 0


def test_supplied_live_tracks_override_resume_reads_and_ignore_initial_selection() -> (
    None
):
    """Resumed Queue 2 reviews use the supplied remaining live queue for both reads."""
    lifecycle, effects, _playlists = _case(fill=False)
    lifecycle.state["active_run"] = _saved()
    live = [SOURCE]
    snapshot = lifecycle.prepare(initial=[], live=live)
    assert (
        snapshot.resumed
        and snapshot.length_before == 1
        and snapshot.live_ids == {"source"}
    )
    assert effects.events == [] and live == [SOURCE]


def test_explicit_initial_and_live_sequences_remain_distinct_for_a_new_run() -> None:
    """Daily review selection limits the snapshot without limiting live membership."""
    lifecycle, effects, _playlists = _case(fill=False)
    snapshot = lifecycle.prepare(initial=[], live=[SOURCE])
    assert snapshot.entries == [] and snapshot.length_before == 0
    assert snapshot.live_ids == {"source"}
    assert _names(effects) == ["checkpoint"]


@pytest.mark.parametrize(
    "raw",
    [None, [], {"status": "done"}, {"status": "active", "playlist_id": "different"}],
)
def test_nonresumable_records_create_a_fresh_run(raw: object) -> None:
    """Only matching active/refilling records suppress new snapshot creation."""
    lifecycle, effects, _playlists = _case(fill=False)
    lifecycle.state["active_run"] = raw
    snapshot = lifecycle.prepare([], [])
    assert not snapshot.resumed and snapshot.run is not raw
    assert _names(effects) == ["checkpoint"]


@pytest.mark.parametrize("status", ["active", "refilling"])
def test_blocking_run_fails_before_live_reads(status: str) -> None:
    """Another active review retains its original blocking error and read boundary."""
    lifecycle, effects, _playlists = _case()
    lifecycle.state["queue_2_active_run"] = {"status": status}
    with pytest.raises(
        NewKidsStateError, match="A saved queue 2 active run must be resumed"
    ):
        lifecycle.prepare()
    assert effects.events == []


def test_preview_ignores_blocking_and_resume_records_without_replacing_them() -> None:
    """Previews make a fresh in-memory snapshot without acknowledging existing runs."""
    lifecycle, effects, _playlists = _case(preview=True, fill=False)
    saved = _saved()
    lifecycle.state.update(active_run=saved, queue_2_active_run={"status": "active"})
    snapshot = lifecycle.prepare([], [])
    assert not snapshot.resumed and snapshot.run is not saved
    assert lifecycle.state["active_run"] is saved and effects.events == []


def test_saved_invalid_entries_fail_between_initial_and_execution_reads() -> None:
    """A malformed entry sequence is validated after the original length observation."""
    lifecycle, effects, playlists = _case()
    saved = _saved()
    saved["entries"] = None
    lifecycle.state["active_run"] = saved
    playlists.reads["kids"] = [(SOURCE,), ()]
    with pytest.raises(NewKidsStateError, match="invalid entries"):
        lifecycle.prepare()
    assert effects.events == [("playlist", "kids")]
    assert playlists.reads["kids"] == [()]


def test_finish_refills_after_status_checkpoint_then_clears_the_run() -> None:
    """Checkpoint refilling before fresh reads and clear the run after transfers."""
    lifecycle, effects, playlists = _case()
    snapshot = lifecycle.prepare([], [])
    effects.events.clear()
    playlists.reads = {"kids": [()], "queue": [(SOURCE,)]}
    summary = lifecycle.finish(snapshot, (), False)
    assert _names(effects) == [
        "checkpoint",
        "playlist",
        "playlist",
        "append",
        "remove",
        "audit",
        "moved",
        "checkpoint",
    ]
    assert (
        snapshot.run["status"] == "refilling" and lifecycle.state["active_run"] is None
    )
    assert summary.playlist_length_after == 1 and summary.postfill[0].action == "moved"


def test_paused_run_retains_state_and_uses_projected_length_without_reads() -> None:
    """Operator pauses avoid refill and preserve the saved active snapshot."""
    lifecycle, effects, _playlists = _case()
    snapshot = lifecycle.prepare([], [SOURCE])
    effects.events.clear()
    summary = lifecycle.finish(snapshot, (), True)
    assert (
        summary.paused and summary.playlist_length_after == 1 and summary.postfill == ()
    )
    assert lifecycle.state["active_run"] is snapshot.run and effects.events == []


@pytest.mark.parametrize("preview", [False, True])
def test_no_refill_finalization_uses_projected_length(preview: bool) -> None:
    """Queue 2 uses the existing live projection and clears only real runs."""
    lifecycle, effects, _playlists = _case(preview=preview, fill=False)
    snapshot = lifecycle.prepare([], [SOURCE])
    effects.events.clear()
    summary = lifecycle.finish(snapshot, (), False)
    assert summary.playlist_length_after == 1 and summary.postfill == ()
    assert _names(effects) == ([] if preview else ["checkpoint"])
    assert ("active_run" in lifecycle.state) is not preview


def test_preview_refill_reloads_live_playlist_instead_of_using_projection() -> None:
    """Original preview behavior refreshes remote membership after simulated review."""
    lifecycle, effects, playlists = _case(preview=True)
    snapshot = lifecycle.prepare([], [SOURCE])
    snapshot.live_ids.clear()
    effects.events.clear()
    playlists.reads["kids"] = [(SOURCE,)]
    summary = lifecycle.finish(snapshot, (), False)
    assert summary.playlist_length_after == 1 and not snapshot.live_ids
    assert _names(effects) == ["playlist", "playlist"]
    assert snapshot.run["status"] == "active" and "active_run" not in lifecycle.state


def test_refilling_checkpoint_failure_precedes_any_final_live_read() -> None:
    """Checkpoint failure leaves the working run refilling without new reads."""
    lifecycle, effects, _playlists = _case()
    snapshot = lifecycle.prepare([], [])
    effects.events.clear()
    effects.fail_at = "checkpoint"
    with pytest.raises(OSError, match="checkpoint"):
        lifecycle.finish(snapshot, (), False)
    assert snapshot.run["status"] == "refilling"
    assert _names(effects) == ["checkpoint"]


def test_custom_run_keys_are_used_for_snapshot_and_clear() -> None:
    """Queue 2 can share lifecycle rules without writing the New Kids active key."""
    lifecycle, effects, _playlists = _case(fill=False)
    lifecycle = replace(
        lifecycle, active_key="queue_2_active_run", blocking_key="active_run"
    )
    snapshot = lifecycle.prepare([], [])
    assert lifecycle.state["queue_2_active_run"] is snapshot.run
    lifecycle.finish(snapshot, (), False)
    assert lifecycle.state["queue_2_active_run"] is None
    assert "active_run" not in lifecycle.state
    assert _names(effects) == ["checkpoint", "checkpoint"]
