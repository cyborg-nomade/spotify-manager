"""Verify whole-album decisions, persistence and unchanged current-album behavior."""

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.slow_listening import flush_slow_listening
from spotify_manager.application.slow_listening_albums import album_skips
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from tests.support.listening_values import release_track
from tests.support.slow_listening_albums import THIRD
from tests.support.slow_listening_albums import AlbumMemory
from tests.support.slow_listening_albums import album_memory
from tests.support.slow_listening_memory import FIRST
from tests.support.slow_listening_memory import SECOND
from tests.support.slow_listening_memory import SOURCE


@pytest.mark.parametrize("preview", [False, True])
async def test_multiple_album_skips_advance_once_without_track_by_track_choices(
    preview: bool,
) -> None:
    """Decline two complete albums before accepting the fourth album's marker.

    Args:
        preview: Suppress remote writes and durable checkpoints.
    """
    memory = album_memory(["skip_album", "skip_album", "advance"])
    before = deepcopy(memory.state)
    summary = await flush_slow_listening("slow", memory.dependencies(), dry_run=preview)
    assert memory.proposed_albums == ["second", "third", "fourth"]
    assert memory.counts.get("choose", 0) == 0
    assert summary.results[0].target_track == "fourth-1"
    assert summary.results[0].skipped_albums == ("Second", "Third")
    assert summary.results[0].skipped_candidates == ()
    assert (
        memory.counts.get("append", 0)
        == memory.counts.get("remove", 0)
        == int(not preview)
    )
    if preview:
        assert memory.state == before and memory.live == [SOURCE]
    else:
        assert [track.spotify_id for track in memory.live] == ["fourth-1"]


async def test_restart_bypasses_rejected_album_prompts_and_track_reads() -> None:
    """A saved rejection bypasses both its prompt and its track read on restart."""
    memory = album_memory(["skip_album", "quit", "advance"])
    paused = await flush_slow_listening("slow", memory.dependencies())
    assert paused.paused and paused.processed == 0
    assert memory.live == [SOURCE]
    memory.events.clear()
    resumed = await flush_slow_listening("slow", memory.dependencies())
    assert resumed.resumed and not resumed.paused
    assert resumed.results[0].target_track == "third-1"
    assert resumed.results[0].skipped_albums == ("Second",)
    assert memory.proposed_albums == ["second", "third", "third"]
    assert ("tracks", "second") not in memory.events


@pytest.mark.parametrize("accepted", [False, True])
async def test_album_skip_checkpoint_failure_preserves_the_accepted_boundary(
    accepted: bool,
) -> None:
    """Restart honors a saved skip or asks again when its checkpoint was rejected.

    Args:
        accepted: Persist the checkpoint before its response fails.
    """
    memory = album_memory(["skip_album"])
    memory.failure, memory.occurrence, memory.accepted = "save", 2, accepted
    with pytest.raises(RuntimeError, match="save interrupted"):
        await flush_slow_listening("slow", memory.dependencies())
    assert memory.live == [SOURCE]
    memory.album_choices = ["advance"] if accepted else ["skip_album", "advance"]
    result = await flush_slow_listening("slow", memory.dependencies())
    assert result.results[0].target_track == "third-1"
    assert memory.proposed_albums.count("second") == (1 if accepted else 2)
    assert memory.counts["append"] == memory.counts["remove"] == 1


@pytest.mark.parametrize("preview", [False, True])
async def test_exhausting_all_proposed_albums_retains_artist_completion_policy(
    preview: bool,
) -> None:
    """Exhaustion completes the artist and acknowledges only an applied completion.

    Args:
        preview: Preview without source removal or completion interaction.
    """
    memory = album_memory(["skip_album"] * 3)
    result = await flush_slow_listening("slow", memory.dependencies(), dry_run=preview)
    assert result.completed_artists == 1 and result.advanced == 0
    assert result.results[0].skipped_albums == ("Second", "Third", "Fourth")
    assert (
        result.results[0].reason == "all remaining studio albums or tracks were skipped"
    )
    assert memory.counts.get("complete", 0) == int(not preview)
    assert memory.counts.get("append", 0) == 0
    assert memory.live == ([SOURCE] if preview else [])


async def test_album_skips_follow_the_saved_equal_date_order() -> None:
    """Reject a tied album without changing the operator's order for its siblings."""
    memory = album_memory(["skip_album", "advance"])
    memory.releases = (FIRST, SECOND, replace(THIRD, chronology_date="2021"))
    memory.order_ids = ("third", "second")
    result = await flush_slow_listening("slow", memory.dependencies())
    assert memory.proposed_albums == ["third", "second"]
    assert result.results[0].target_track == "second-1"
    assert result.results[0].skipped_albums == ("Third",)
    assert memory.counts["order"] == 1


@pytest.mark.parametrize("alternate_edition", [False, True])
async def test_current_album_keeps_its_original_track_interaction(
    alternate_edition: bool,
) -> None:
    """Do not expose album rejection while advancing inside the mapped edition.

    Args:
        alternate_edition: The playlist marker comes from another equivalent edition.
    """
    source = SOURCE
    if alternate_edition:
        source = replace(SOURCE, release=replace(SOURCE.release, spotify_id="other"))
    memory = AlbumMemory(
        live=[source],
        release_tracks={"first": (release_track("source"), release_track("next"))},
    )
    result = await flush_slow_listening("slow", memory.dependencies())
    assert result.results[0].target_track == "next"
    assert memory.counts["choose"] == 1 and not memory.proposed_albums


async def test_single_track_skips_remain_available_inside_a_proposed_album() -> None:
    """Skipping one proposed marker does not reject its album implicitly."""
    memory = album_memory(["skip", "advance"])
    result = await flush_slow_listening("slow", memory.dependencies())
    assert result.results[0].target_track == "second-2"
    assert result.results[0].skipped_albums == ()
    assert result.results[0].skipped_candidates == ("second-1 (Second)",)
    assert memory.proposed_albums == ["second", "second"]


async def test_compatibility_reader_still_honors_persisted_album_skips() -> None:
    """A restart without the new interaction cannot forget accepted rejections."""
    memory = album_memory(["skip_album", "quit"])
    await flush_slow_listening("slow", memory.dependencies())
    dependencies = replace(memory.dependencies(), release_choice=None)
    result = await flush_slow_listening("slow", dependencies)
    assert result.results[0].target_track == "third-1"
    assert result.results[0].skipped_albums == ("Second",)
    assert memory.proposed_albums == ["second", "third"]


@pytest.mark.parametrize("raw", [[], None, {"album": 1}, {"": "Album"}, {1: "Album"}])
def test_invalid_album_skip_state_is_never_silently_discarded(raw: object) -> None:
    """Reject malformed additive state instead of reoffering rejected releases.

    Args:
        raw: Malformed stored edition/name mapping.
    """
    with pytest.raises(SlowListeningStateError, match="invalid skipped albums"):
        album_skips({"skipped_albums": raw})


async def test_invalid_album_choices_fail_without_mutation() -> None:
    """An unsupported action cannot become an implicit track or album rejection."""
    memory = album_memory(["invalid"])
    with pytest.raises(SlowListeningError, match="Album action"):
        await flush_slow_listening("slow", memory.dependencies())
    assert memory.live == [SOURCE] and not memory.audits
    run = cast(dict[str, object], memory.state["active_run"])
    assert "skipped_albums" not in cast(list[dict[str, object]], run["entries"])[0]


async def test_accepted_target_plan_retains_album_skips_after_append_interruption() -> (
    None
):
    """Resume a planned transition without another album choice or duplicate append."""
    memory = album_memory(["skip_album", "advance"])
    memory.failure, memory.accepted = "append", True
    with pytest.raises(RuntimeError, match="append interrupted"):
        await flush_slow_listening("slow", memory.dependencies())
    result = await flush_slow_listening("slow", memory.dependencies())
    assert result.resumed and result.results[0].target_track == "third-1"
    assert result.results[0].skipped_albums == ("Second",)
    assert memory.proposed_albums == ["second", "third"]
    assert memory.counts["append"] == memory.counts["remove"] == 1


async def test_old_track_reader_cannot_invent_an_album_skip_on_resume() -> None:
    """A reader without album interaction must use its original track action set."""
    memory = album_memory(["skip_album", "quit"])
    await flush_slow_listening("slow", memory.dependencies())
    memory.choices = ["skip_album"]
    dependencies = replace(memory.dependencies(), release_choice=None)
    with pytest.raises(SlowListeningError, match="Track action"):
        await flush_slow_listening("slow", dependencies)
    assert memory.live == [SOURCE]
