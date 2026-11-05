"""Verify actual marker order and durable recovery across mixed New Wine transitions."""

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.new_wine import flush_new_wine
from tests.support.new_wine_memory import OPTIONS
from tests.support.new_wine_memory import MemoryWine
from tests.support.new_wine_memory import dependencies
from tests.support.wine_improvements import PlaylistEdit
from tests.support.wine_improvements import marker_ids
from tests.support.wine_improvements import mixed_wine
from tests.support.wine_improvements import single_and_advance


def _remaining_choices(memory: MemoryWine) -> list[str]:
    run = cast(dict[str, object], memory.stored.get("active_run") or {})
    if not run:
        return ["a-new", "c-new"]
    entries = cast(list[dict[str, object]], run["entries"])
    choices = []
    for entry in entries:
        source = cast(dict[str, object], entry["source"])
        if entry.get("plan") is not None:
            continue
        if source["spotify_id"] == "a-end":
            choices.append("a-new")
        if source["spotify_id"] == "c-end":
            choices.append("c-new")
    return choices


@pytest.mark.parametrize("preview", [False, True])
async def test_mixed_transitions_advance_before_new_records(preview: bool) -> None:
    """A's and C's new records follow B's continuation in stable encounter order.

    Args:
        preview: Whether to suppress live effects and checkpoints.
    """
    memory = mixed_wine()
    before = deepcopy(memory.playlists)
    result = await flush_new_wine(
        replace(OPTIONS, dry_run=preview), dependencies(memory)
    )
    assert [item.source_track for item in result.results] == [
        "b-start",
        "a-end",
        "c-end",
    ]
    assert (result.advanced, result.sent_to_sauvignon, result.processed) == (1, 2, 3)
    if preview:
        assert memory.playlists == before
        assert memory.stored["active_run"] is None
        return
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]
    assert marker_ids(memory.playlists["sauvignon"]) == ["a-end", "c-end"]


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("occurrence", [1, 2, 3, 4, 5])
async def test_append_interruptions_preserve_final_order(
    accepted: bool, occurrence: int
) -> None:
    """A fresh invocation consumes saved plans without reordering or duplicating.

    Args:
        accepted: Whether Spotify accepted the interrupted append.
        occurrence: Each continuation, Sauvignon or new-record append boundary.
    """
    memory = mixed_wine()
    memory.failure, memory.accepted, memory.occurrence = "append", accepted, occurrence
    with pytest.raises(RuntimeError, match="append interrupted"):
        await flush_new_wine(OPTIONS, dependencies(memory))
    memory.choices = _remaining_choices(memory)
    result = await flush_new_wine(OPTIONS, dependencies(memory))
    assert result.resumed and not result.paused
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]
    assert marker_ids(memory.playlists["sauvignon"]) == ["a-end", "c-end"]


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("occurrence", [1, 2, 3])
async def test_removal_interruptions_retain_replacement_before_source(
    accepted: bool, occurrence: int
) -> None:
    """Every removed source already has its replacement, including deferred entries.

    Args:
        accepted: Whether the interrupted removal was accepted.
        occurrence: B, A or C source-removal boundary.
    """
    memory = mixed_wine()
    memory.failure, memory.accepted, memory.occurrence = "remove", accepted, occurrence
    with pytest.raises(RuntimeError, match="remove interrupted"):
        await flush_new_wine(OPTIONS, dependencies(memory))
    memory.choices = _remaining_choices(memory)
    await flush_new_wine(OPTIONS, dependencies(memory))
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("occurrence", [1, 2, 3, 4, 5, 6, 7, 8])
async def test_checkpoint_interruptions_reconstruct_deferred_order(
    accepted: bool, occurrence: int
) -> None:
    """Durable plans and statuses are sufficient to rebuild the remaining groups.

    Args:
        accepted: Whether the interrupted checkpoint was accepted.
        occurrence: Initial, planning, completion or final run checkpoint.
    """
    memory = mixed_wine()
    memory.failure, memory.accepted, memory.occurrence = "save", accepted, occurrence
    with pytest.raises(RuntimeError, match="save interrupted"):
        await flush_new_wine(OPTIONS, dependencies(memory))
    run = cast(dict[str, object], memory.stored.get("active_run") or {})
    if run.get("status") == "completed":
        assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]
        return
    memory.choices = _remaining_choices(memory)
    await flush_new_wine(OPTIONS, dependencies(memory))
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]


async def test_pause_retains_accepted_plan_without_appending_it_early() -> None:
    """Quit at C keeps A's saved decision and B's accepted continuation for resume."""
    memory = mixed_wine()
    memory.choices = ["a-new", "quit"]
    paused = await flush_new_wine(OPTIONS, dependencies(memory))
    assert paused.paused and paused.processed == 1
    assert marker_ids(memory.playlists["new"]) == ["a-end", "c-end", "b-next"]
    memory.choices = ["c-new"]
    resumed = await flush_new_wine(OPTIONS, dependencies(memory))
    assert resumed.resumed and not resumed.paused
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]


async def test_single_selecting_another_release_also_starts_at_the_tail() -> None:
    """A new album selected from a single follows all within-album advances."""
    memory = single_and_advance()
    await flush_new_wine(OPTIONS, dependencies(memory))
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first"]


async def test_cancellation_before_deferred_effects_keeps_saved_plans() -> None:
    """The new effect phase observes cancellation before starting a new record."""
    memory = mixed_wine()
    memory.failure, memory.occurrence = "progress", 5
    with pytest.raises(RuntimeError, match="progress interrupted"):
        await flush_new_wine(OPTIONS, dependencies(memory))
    assert marker_ids(memory.playlists["new"]) == ["a-end", "c-end", "b-next"]
    memory.choices.clear()
    await flush_new_wine(OPTIONS, dependencies(memory))
    assert marker_ids(memory.playlists["new"]) == ["b-next", "a-first", "c-first"]


@pytest.mark.parametrize("remove_source", [False, True])
async def test_deferred_phase_refreshes_membership_after_later_prompts(
    remove_source: bool,
) -> None:
    """External tail edits remain, and an absent source cannot start another record.

    Args:
        remove_source: Whether the edit consumes A or appends an unrelated marker.
    """
    memory = mixed_wine()
    resources = replace(
        dependencies(memory), progress=PlaylistEdit(memory, remove_source)
    )
    await flush_new_wine(OPTIONS, resources)
    expected = (
        ["b-next", "c-first"]
        if remove_source
        else ["b-next", "external-tail", "a-first", "c-first"]
    )
    assert marker_ids(memory.playlists["new"]) == expected
