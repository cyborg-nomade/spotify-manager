"""Verify exporter batch order, retry safety and destination conflicts."""

import pytest

from spotify_manager.application.listening_export import PlaylistExportJob
from spotify_manager.application.listening_export import run_playlist_export
from spotify_manager.domain.listening_export import ExportPlan
from spotify_manager.domain.listening_export import ExportSources
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.domain.listening_export import ExportTrack
from spotify_manager.infrastructure.async_signal import AsyncSignal
from tests.support.listening_export import OWNED
from tests.support.listening_export import PRIVATE
from tests.support.listening_export import FixturePlaylistGateway
from tests.support.listening_export import ImmediateStop


def _job(
    gateway: FixturePlaylistGateway, count: int, new: bool = False
) -> PlaylistExportJob:
    tracks = tuple(
        ExportTrack(f"spotify:track:{index:022d}", "Title", "Artist")
        for index in range(count)
    )
    plan = ExportPlan(
        ExportSources("history", "library"),
        ExportTarget("Proposed", "owner", None if new else gateway.lists[OWNED]),
        tracks,
    )
    return PlaylistExportJob("id", plan)


@pytest.mark.asyncio
async def test_resume_preserves_completed_batches_after_a_rate_limit() -> None:
    """Retry a rejected write without repeating the earlier full batch."""
    gateway = FixturePlaylistGateway()
    gateway.reject_at = 2
    job = _job(gateway, 103, new=True)
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "paused" and job.added == 100
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "complete" and job.added == 103
    assert gateway.creates == 1
    assert [len(batch) for batch in gateway.writes] == [100, 3, 3]
    assert gateway.tracks[PRIVATE] == [track.uri for track in job.plan.tracks]


@pytest.mark.asyncio
async def test_ambiguous_partial_request_is_reobserved_without_duplicate_writes() -> (
    None
):
    """Keep an uncertain batch pending until its exact complete effect is visible."""
    gateway = FixturePlaylistGateway()
    gateway.split = 2
    gateway.ambiguous = True
    job = _job(gateway, 3)
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "paused" and job.observed == 2 and job.added == 0
    await run_playlist_export(job, gateway, ImmediateStop())
    assert len(gateway.writes) == 1 and job.status == "paused"
    gateway.commit_items(OWNED, (job.plan.tracks[-1].uri,))
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "complete" and job.added == 3 and len(gateway.writes) == 1


@pytest.mark.asyncio
async def test_acknowledged_partial_append_continues_from_observed_prefix() -> None:
    """Use a stable acknowledged snapshot to continue after selected rows land."""
    gateway = FixturePlaylistGateway()
    gateway.split = 2
    job = _job(gateway, 3)
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "complete"
    assert gateway.writes[-1] == (job.plan.tracks[-1].uri,)
    assert len(gateway.tracks[OWNED]) == 4


@pytest.mark.asyncio
async def test_a_changed_destination_fails_before_additions() -> None:
    """Reject an existing playlist edited after the review was prepared."""
    gateway = FixturePlaylistGateway()
    job = _job(gateway, 3)
    gateway.commit_items(OWNED, (job.plan.tracks[-1].uri,))
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "failed"
    assert not gateway.writes


@pytest.mark.asyncio
async def test_lost_playlist_creation_response_cannot_create_twice() -> None:
    """Recover one private destination via its original creation marker."""
    gateway = FixturePlaylistGateway()
    gateway.hide_creation = True
    job = _job(gateway, 3, new=True)
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "paused" and not gateway.writes
    gateway.hide_creation = False
    await run_playlist_export(job, gateway, ImmediateStop())
    assert job.status == "complete" and gateway.creates == 1


@pytest.mark.asyncio
async def test_pause_before_first_mutation_keeps_spotify_idle() -> None:
    """A pause accepted before the worker starts leaves the destination alone."""
    gateway = FixturePlaylistGateway()
    job = _job(gateway, 3, new=True)
    stop = AsyncSignal()
    stop.set()
    await run_playlist_export(job, gateway, stop)
    assert job.status == "paused"
    assert gateway.creates == 0 and not gateway.writes
