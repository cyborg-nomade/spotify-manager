"""Existing artist plans preserve current markers, backups and resumable choices."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from typing import cast

import pytest

from spotify_manager.application.discovery_queue import DiscoveryQueueTransfer
from spotify_manager.application.discovery_run import DiscoveryRun
from spotify_manager.application.new_kids_migration import NewKidsPlanMigration
from spotify_manager.application.new_kids_migration_selection import (
    NewKidsMigrationSelection,
)
from spotify_manager.application.new_kids_plan_records import saved_plan
from spotify_manager.application.new_kids_plan_selection import ReleasePlanStoppedError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.new_kids_plans import plan_marker
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.new_kids_plan_memory import PlanMemory


class MigrationMemory(PlanMemory):
    """Add deterministic time and output to the existing durable plan simulation."""

    def now(self) -> datetime:
        """Return a stable migration backup timestamp.

        Returns:
            Aware test-only UTC instant.
        """
        return datetime(2026, 11, 5, tzinfo=UTC)

    def echo(self, message: str) -> None:
        """Record migration progress.

        Args:
            message: Complete operator message.
        """
        self.events.append(("echo", message))


def _memory() -> MigrationMemory:
    memory = MigrationMemory()
    ids = ("old", "before", "current", "next")
    memory.catalogs["artist"] = tuple(release(key) for key in ids)
    memory.releases["current"] = (track("first"), track("middle"), track("last"))
    memory.answers = [
        ReleasePlanSubmission("select", ("old", "before", "current", "next"))
    ]
    memory.persisted["artists"] = {
        "artist": {
            "artist_name": "Artist",
            "prior_unliked_streak": 2,
            "retained": "value",
        }
    }
    return memory


def _stage(
    memory: MigrationMemory, state: dict[str, object], preview: bool = False
) -> NewKidsPlanMigration:
    return NewKidsPlanMigration(
        NewKidsMigrationSelection(memory, memory),
        memory,
        state,
        memory,
        memory,
        preview,
    )


def _source() -> list[PlaylistTrack]:
    return [plan_marker(release("current"), track("middle"))]


async def test_backup_precedes_acceptance_and_keeps_current_track_and_streak() -> None:
    """Earlier ordered releases are completed without resetting the marker."""
    memory = _memory()
    original = await memory.load()
    state = deepcopy(original)
    await _stage(memory, state).run(_source())
    backup = cast(dict[str, object], memory.persisted["release_plan_migration_backup"])
    assert backup["namespace"] == original
    assert memory.snapshots[0]["artists"] == original["artists"]
    artists = cast(dict[str, dict[str, object]], memory.persisted["artists"])
    plan = saved_plan(artists["artist"])
    assert plan is not None and plan.position == 2
    assert artists["artist"]["prior_unliked_streak"] == 2
    assert artists["artist"]["release_plan_marker"] == {
        "track_id": "middle",
        "release_id": "current",
    }
    assert len(memory.snapshots) == 2 and not memory.playlists
    await _stage(memory, await memory.load()).run(_source())
    assert len(memory.drafts) == 1 and len(memory.snapshots) == 2


async def test_partial_migration_resumes_only_the_remaining_artist() -> None:
    """A later quit cannot discard or re-prompt an earlier accepted plan."""
    memory = _memory()
    other = replace(
        release("other"), primary_artist_id="other", primary_artist_name="Other"
    )
    other_track = replace(
        track("other-track"), primary_artist_id="other", primary_artist_name="Other"
    )
    memory.catalogs["other"] = (other,)
    memory.releases["other"] = (other_track,)
    sources = [*_source(), plan_marker(other, other_track)]
    memory.answers.append(ReleasePlanSubmission("quit"))
    with pytest.raises(ReleasePlanStoppedError):
        await _stage(memory, await memory.load()).run(sources)
    memory.answers = [ReleasePlanSubmission("select", ("other",), True)]
    await _stage(memory, await memory.load()).run(sources)
    assert [draft.artist for draft in memory.drafts] == ["Artist", "Other", "Other"]
    assert len(memory.snapshots) == 3


@pytest.mark.parametrize("preview", [False, True])
async def test_skip_excludes_unplanned_artist_from_this_runs_legacy_review(
    preview: bool,
) -> None:
    """Deferral leaves the marker intact and prevents a history-based fallback.

    Args:
        preview: Whether migration uses a detached namespace projection.
    """
    memory = _memory()
    memory.answers = [ReleasePlanSubmission("skip")]
    stage = _stage(memory, await memory.load(), preview)
    await stage.run(_source())
    assert stage.review_markers(_source()) == [] and memory.snapshots == []


async def test_preview_projects_plan_without_backup_or_checkpoint() -> None:
    """Preview lets subsequent planning see the accepted cursor without saving it."""
    memory = _memory()
    before = await memory.load()
    state = deepcopy(before)
    await _stage(memory, state, True).run(_source())
    assert memory.persisted == before and memory.snapshots == []
    artists = cast(dict[str, dict[str, object]], state["artists"])
    assert saved_plan(artists["artist"]) is not None
    assert "release_plan_migration_backup" not in state


async def test_backup_failure_stops_before_an_artist_plan_is_saved() -> None:
    """An unacknowledged backup cannot permit migration to proceed."""
    memory = _memory()
    before = await memory.load()
    memory.fail_at = "save"
    with pytest.raises(OSError):
        await _stage(memory, deepcopy(before)).run(_source())
    assert memory.persisted == before


async def test_ambiguous_current_edition_requires_explicit_resolution() -> None:
    """A title-only marker is not silently treated as a known exact edition."""
    memory = _memory()
    source = replace(_source()[0], spotify_id="legacy", uri="spotify:track:legacy")
    memory.answers = [
        ReleasePlanSubmission("select", ("current",), True),
        ReleasePlanSubmission("select", ("current",), True, "current", True),
    ]
    await _stage(memory, await memory.load()).run([source])
    assert memory.drafts[0].current_release_id is None
    assert "Choose the current album" in memory.drafts[1].notice
    assert memory.snapshots


def _lifecycle(memory: MigrationMemory, state: dict[str, object]) -> DiscoveryRun:
    transfer = DiscoveryQueueTransfer(
        memory, memory, memory, "kids", "queue", 10, False
    )
    return DiscoveryRun(
        memory,
        transfer,
        state,
        "kids",
        "active_run",
        "queue_2_active_run",
        False,
        False,
        memory,
        _stage(memory, state),
    )


async def test_saved_review_defers_migration_to_the_next_fresh_run() -> None:
    """Existing accepted entries resume without changing their plan boundary."""
    memory = _memory()
    state = await memory.load()
    saved = {"status": "active", "playlist_id": "kids", "entries": []}
    state["active_run"] = saved
    snapshot = await _lifecycle(memory, state).prepare(live=_source())
    assert snapshot.resumed and snapshot.run is saved
    assert not memory.drafts and not memory.snapshots
    assert "next fresh run" in str(memory.events[-1])


async def test_blocking_queue_review_precedes_migration_interaction() -> None:
    """An unfinished Queue 2 run blocks before any new artist is offered."""
    memory = _memory()
    state = await memory.load()
    state["queue_2_active_run"] = {"status": "active"}
    with pytest.raises(NewKidsStateError, match="must be resumed"):
        await _lifecycle(memory, state).prepare(initial=_source())
    assert not memory.drafts and not memory.snapshots


async def test_corrupt_backup_is_preserved_and_blocks_new_plan_checkpoint() -> None:
    """A malformed prior backup cannot be overwritten by a new migration."""
    memory = _memory()
    memory.persisted["release_plan_migration_backup"] = {"version": 99}
    before = await memory.load()
    with pytest.raises(NewKidsStateError, match="backup is invalid"):
        await _stage(memory, deepcopy(before)).run(_source())
    assert memory.persisted == before and not memory.snapshots


async def test_current_edition_missing_from_canonical_catalogue_stays_available() -> (
    None
):
    """Canonical edition deduplication cannot drop the exact live album."""
    memory = _memory()
    memory.catalogs["artist"] = (release("next"),)
    memory.answers = [ReleasePlanSubmission("select", ("current", "next"), True)]
    await _stage(memory, await memory.load()).run(_source())
    assert memory.drafts[0].current_release_id == "current"
    assert [item.spotify_id for item in memory.drafts[0].releases] == [
        "current",
        "next",
    ]


async def test_migration_keeps_logical_composer_and_current_performer_credit() -> None:
    """A routed performer marker remains under the logical composer plan."""
    memory = _memory()
    memory.catalogs["composer"] = memory.catalogs["artist"]
    memory.persisted["composer_routes"] = {
        "composer": {"artist_name": "Composer", "current_track_id": "middle"}
    }
    await _stage(memory, await memory.load()).run(_source())
    artists = cast(dict[str, dict[str, object]], memory.persisted["artists"])
    plan = saved_plan(artists["composer"])
    assert (
        plan is not None and plan.releases[plan.position].primary_artist_id == "artist"
    )
    assert memory.drafts[0].artist == "Composer"
