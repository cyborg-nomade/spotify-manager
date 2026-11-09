"""Verify bounded discovery after recovery, including skips, preview and resume."""

from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.wine_cellar import CellarOptions
from spotify_manager.application.wine_cellar import CellarWorkflow
from tests.support.cellar_memory import MemoryCellar
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release
from tests.support.wine_improvements import TransferReader


RELEASE = studio_release("release", "Release")
KNOWN = replace(playlist_track("known", RELEASE), primary_artist_name="Known")
UNKNOWN = replace(playlist_track("unknown", RELEASE), primary_artist_name="Unknown")
EXTRA = replace(UNKNOWN, spotify_id="extra", uri="spotify:track:extra")


async def _refill(
    memory: MemoryCellar,
    reader: TransferReader,
    *,
    target: int = 10,
    dry_run: bool = False,
) -> CellarRefillSummary:
    state = deepcopy(memory.stored)
    run = cast(
        dict[str, object],
        state.setdefault("active_run", {"run_id": "run", "refill_pending": None}),
    )
    options = CellarOptions(
        "new", "cellar", not bool(run.get("discovery_fallback")), dry_run, target
    )
    return await CellarWorkflow(memory, memory, reader).run(options, state, run)


@pytest.mark.parametrize("dry_run", [False, True])
async def test_recovery_then_discovery_fills_only_remaining_capacity(
    dry_run: bool,
) -> None:
    """Known artists precede discovery and later markers remain untouched.

    Args:
        dry_run: Whether to preserve every remote playlist and checkpoint.
    """
    memory = MemoryCellar(
        {"new": [], "cellar": [UNKNOWN, KNOWN, EXTRA]},
        eligibility={"known": (18, 0, True)},
    )
    before = deepcopy(memory.playlists)
    reader = TransferReader(["accept"])
    result = await _refill(memory, reader, target=2, dry_run=dry_run)
    assert result.after == 2 and result.added == 2 and result.discovery_fallback
    assert not result.no_discovery
    assert reader.offered == [("known", 18, 0)]
    assert [row.source_track for row in result.results if row.action == "moved"] == [
        KNOWN.name,
        UNKNOWN.name,
    ]
    if dry_run:
        assert memory.playlists == before and memory.stored == {}
        return
    assert memory.playlists == {"new": [KNOWN, UNKNOWN], "cellar": [EXTRA]}


async def test_sufficient_recovery_never_enables_discovery() -> None:
    """The exception is unused when recovery fills the destination."""
    memory = MemoryCellar(
        {"new": [], "cellar": [KNOWN, UNKNOWN]}, eligibility={"known": (18, 0, True)}
    )
    result = await _refill(memory, TransferReader(["accept"]), target=1)
    assert result.after == 1 and result.no_discovery and not result.discovery_fallback
    assert memory.playlists["cellar"] == [UNKNOWN]
    assert memory.calls["counts"] == 1


async def test_no_sources_never_fabricates_a_full_playlist() -> None:
    """An empty recovery and discovery source leaves the actual empty count."""
    memory = MemoryCellar({"new": [], "cellar": []})
    result = await _refill(memory, TransferReader())
    assert result.after == 0 and result.added == 0 and result.discovery_fallback
    assert not result.no_discovery and memory.playlists["new"] == []


async def test_explicit_skip_is_preserved_when_discovery_is_enabled() -> None:
    """Capacity fallback cannot undo an operator's rejected transfer."""
    memory = MemoryCellar(
        {"new": [], "cellar": [KNOWN, UNKNOWN]}, eligibility={"known": (18, 0, True)}
    )
    reader = TransferReader(["skip"])
    result = await _refill(memory, reader, target=1)
    assert result.discovery_fallback and result.after == 1
    assert reader.offered == [("known", 18, 0)]
    assert memory.playlists == {"new": [UNKNOWN], "cellar": [KNOWN]}
    assert [row.action for row in result.results] == ["skipped", "ineligible", "moved"]


async def test_fallback_resume_preserves_accepted_transfer_order() -> None:
    """An accepted append resumes by securing removal without adding it twice."""
    memory = MemoryCellar(
        {"new": [], "cellar": [KNOWN, UNKNOWN]},
        eligibility={"known": (18, 0, True)},
        failure="append",
        accepted=True,
        occurrence=2,
    )
    with pytest.raises(RuntimeError, match="append interrupted"):
        await _refill(memory, TransferReader(["accept"]), target=2)
    assert memory.playlists["new"] == [KNOWN, UNKNOWN]
    resumed = await _refill(memory, TransferReader(), target=2)
    assert resumed.after == 2 and resumed.added == 0 and resumed.discovery_fallback
    assert memory.calls["append"] == 2 and memory.playlists["cellar"] == []


async def test_operator_pause_never_enters_fallback() -> None:
    """Quit remains authoritative even while the destination is under capacity."""
    memory = MemoryCellar(
        {"new": [], "cellar": [KNOWN, UNKNOWN]}, eligibility={"known": (18, 0, True)}
    )
    result = await _refill(memory, TransferReader(["quit"]))
    assert result.paused and not result.discovery_fallback and result.added == 0
    assert memory.playlists == {"new": [], "cellar": [KNOWN, UNKNOWN]}
