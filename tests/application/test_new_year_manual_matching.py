"""Dropped annual entries remain visible while accepted markers complete safely."""

from typing import cast
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_retry import AnnualRetry
from spotify_manager.application.new_year_run import NewYear
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.domain.annual_history import accepted_uris
from tests.application.test_historical_resolution import _match
from tests.application.test_new_year_workflow import AnnualCancellation
from tests.application.test_new_year_workflow import MemoryAnnual
from tests.application.test_new_year_workflow import ScriptedDiscoveries
from tests.application.test_new_year_workflow import ScriptedHistory
from tests.support.manual_matching import AlbumSearch
from tests.support.manual_matching import CatalogChoices
from tests.support.manual_matching import TrackSearch
from tests.support.manual_matching import album_candidate
from tests.support.new_year_run import AnnualObservations


def _workflow(edge: AnnualObservations, choices: CatalogChoices) -> NewYear:
    retry = AnnualRetry(edge, AnnualCancellation(edge))
    memory = MemoryAnnual(edge, retry)
    candidates = (_match("a-One", 0.01), _match("b-Two", 0.01))
    tracks = ManualTrackMatching(TrackSearch(candidates), choices, choices)
    albums = ManualAlbumMatching(AlbumSearch((album_candidate(),)), choices, choices)
    resolution = AnnualResolution(memory, tracks, albums, edge)
    discoveries = cast(AnnualDiscoveries, ScriptedDiscoveries(memory))
    members = AnnualMembership(memory, retry)
    planner = AnnualPlanning(
        cast(HistoryRefresh, ScriptedHistory(memory)),
        "listener",
        memory,
        resolution,
        edge,
        ZoneInfo("Europe/Berlin"),
    )
    return NewYear(
        memory,
        planner,
        AnnualExecution(
            memory, AnnualCharts(memory, members, retry), members, discoveries
        ),
        discoveries,
    )


@pytest.mark.parametrize("preview", [False, True])
async def test_dropping_one_track_keeps_accepted_plan_charts_and_artist_markers(
    preview: bool,
) -> None:
    """Carry rejection through planning and execution without aborting later entries.

    Args:
        preview: Suppress live/durable writes while retaining the complete plan.
    """
    edge = AnnualObservations("no-track")
    choices = CatalogChoices(["", "b-Two", ""])
    result = await _workflow(edge, choices).run(2025, preview)
    plan = cast(RetrospectivePlan, result["plan"])
    assert plan["tracks"][0]["dropped"] is True
    assert "uri" not in plan["tracks"][0]
    assert plan["artists"][0]["dropped"] is True
    assert accepted_uris(plan["tracks"]) == ["spotify:track:b-Two"]
    assert accepted_uris(plan["artists"]) == ["spotify:track:b-Two"]
    assert len(choices.offered) == 3
    if preview:
        assert edge.state == {"years": {}}
        assert not any(
            event[0] in {"post", "replace", "create"} for event in edge.trace
        )
    else:
        chart = next(
            item for item in edge.playlists if item.name == "top 50 2025 tracks"
        )
        assert edge.contents[chart.spotify_id] == ["spotify:track:b-Two"]
        assert edge.contents["memory"][0] == "spotify:track:b-Two"


async def test_album_rejection_keeps_other_release_markers_and_records_the_drop() -> (
    None
):
    """Resolve albums with album choices rather than asking the operator for tracks."""
    edge = AnnualObservations("no-album")
    choices = CatalogChoices(["", "album"])
    result = await _workflow(edge, choices).run(2025, True)
    plan = cast(RetrospectivePlan, result["plan"])
    assert plan["albums"][0]["dropped"] is True
    assert plan["albums"][1]["uri"] == "first-album"
    assert all(reference.track == "" for reference, _options in choices.offered)
    assert len(choices.offered) == 2


async def test_stored_plan_with_drops_resumes_without_reopening_operator_choices() -> (
    None
):
    """Retain explicit rejections across execution and checkpoint recovery."""
    edge = AnnualObservations("no-track")
    preview = await _workflow(edge, CatalogChoices(["", "b-Two", ""])).run(2025, True)
    plan = cast(RetrospectivePlan, preview["plan"])
    edge.state = {"years": {"2025": {"completed": [], "plan": plan}}}
    choices = CatalogChoices()
    result = await _workflow(edge, choices).run(2025, False)
    assert result["done"] is True
    assert choices.offered == []
    assert cast(RetrospectivePlan, result["plan"])["tracks"][0]["dropped"] is True


async def test_unknown_artist_can_be_rejected_or_mapped_by_an_explicit_marker() -> None:
    """Let artist-level unresolved entries participate in selection and dropping."""
    edge = AnnualObservations("no-artist")
    choices = CatalogChoices(["", "b-Two"])
    result = await _workflow(edge, choices).run(2025, True)
    plan = cast(RetrospectivePlan, result["plan"])
    assert plan["artists"][0]["dropped"] is True
    assert plan["artists"][1]["artist_id"] == "artist-b"
    assert plan["artists"][1]["uri"] == "spotify:track:b-Two"
    assert all(reference.track == "" for reference, _options in choices.offered)


async def test_artist_marker_retries_before_accepting_primary_artist() -> None:
    """Keep Memory Lane's primary-artist rule after an explicit track choice."""
    edge = AnnualObservations("normal")
    choices = CatalogChoices(["b-Two", "a-One"])
    workflow = _workflow(edge, choices)
    result = await workflow.planning.resolution.marker(
        {"artist": "Alpha", "name": "Alpha", "scrobbles": 10}, "artist-a"
    )
    assert result == "spotify:track:a-One"
    assert len(choices.offered) == 2
    assert any("Different primary artist" in str(event) for event in edge.trace)


async def test_cancelled_matching_never_saves_or_applies_partial_plan() -> None:
    """Stop before any annual state or playlist mutation when matching is cancelled."""
    edge = AnnualObservations("no-track")
    with pytest.raises(BlastFromPastCancelledError):
        await _workflow(edge, CatalogChoices(cancel_at=1)).run(2025, False)
    assert edge.state == {"years": {}}
    assert not any(
        event[0] in {"post", "put", "replace", "create"} for event in edge.trace
    )
