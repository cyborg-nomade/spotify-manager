"""Explicit no-discovery decisions, durable skips and accepted transfer recovery."""

from copy import deepcopy
from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import NewWineStateError
from spotify_manager.application.wine_cellar import CellarOptions
from spotify_manager.application.wine_cellar import CellarWorkflow
from tests.support.cellar_memory import MemoryCellar
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release
from tests.support.wine_improvements import TransferReader


RELEASE = studio_release("release", "Release")
SOURCE = playlist_track("source", RELEASE)
OTHER = playlist_track("other", RELEASE)
OPTIONS = CellarOptions("new", "cellar", True, False, 1)


def _memory() -> MemoryCellar:
    return MemoryCellar(
        {"new": [], "cellar": [SOURCE, OTHER]}, eligibility={"artist": (18, 2, True)}
    )


async def _review(
    memory: MemoryCellar, reader: TransferReader, options: CellarOptions = OPTIONS
) -> CellarRefillSummary:
    state = deepcopy(memory.stored)
    run = cast(
        dict[str, object],
        state.setdefault("active_run", {"run_id": "run", "refill_pending": None}),
    )
    return await CellarWorkflow(memory, memory, reader).run(options, state, run)


@pytest.mark.parametrize("preview", [False, True])
async def test_skip_keeps_source_and_accepts_following_candidate(preview: bool) -> None:
    """Skipping consumes no capacity and repeated source IDs are not reprompted.

    Args:
        preview: Whether all remote and durable effects must be suppressed.
    """
    memory = _memory()
    memory.playlists["cellar"] = [SOURCE, SOURCE, OTHER]
    before = deepcopy(memory.playlists)
    reader = TransferReader(["skip", "accept"])
    options = CellarOptions("new", "cellar", True, preview, 1)
    result = await _review(memory, reader, options)
    assert [item.action for item in result.results] == ["skipped", "moved"]
    assert reader.offered == [("source", 18, 2), ("other", 18, 2)]
    assert (result.added, result.after, result.ineligible, result.paused) == (
        1,
        1,
        0,
        False,
    )
    if preview:
        assert memory.playlists == before and memory.stored == {}
        return
    assert memory.playlists == {"new": [OTHER], "cellar": [SOURCE, SOURCE]}
    run = cast(dict[str, object], memory.stored["active_run"])
    assert run["refill_skipped"] == ["source"] and run["refill_pending"] is None


async def test_quit_preserves_skips_and_reoffers_current_candidate() -> None:
    """Quit does not create an intent; accepted skips survive a fresh session."""
    memory = _memory()
    first = TransferReader(["skip", "quit"])
    result = await _review(memory, first)
    assert result.paused and result.added == 0
    assert memory.playlists == {"new": [], "cellar": [SOURCE, OTHER]}
    second = TransferReader(["accept"])
    resumed = await _review(memory, second)
    assert not resumed.paused and resumed.added == 1
    assert second.offered == [("other", 18, 2)]


async def test_ineligible_marker_is_not_offered_for_confirmation() -> None:
    """The original affinity threshold still controls which markers are offered."""
    memory = _memory()
    memory.eligibility.clear()
    reader = TransferReader()
    result = await _review(memory, reader)
    assert result.ineligible == 2 and result.added == 1
    assert result.discovery_fallback and not result.no_discovery
    assert reader.offered == [] and memory.playlists["new"] == [SOURCE]


async def test_standard_mode_keeps_automatic_transfer_contract() -> None:
    """A supplied reader does not add a prompt in discovery mode."""
    memory = _memory()
    reader = TransferReader()
    result = await _review(
        memory, reader, CellarOptions("new", "cellar", False, False, 1)
    )
    assert result.added == 1 and reader.offered == []


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("boundary", ["append", "remove"])
async def test_confirmed_intent_resumes_without_another_prompt(
    accepted: bool, boundary: str
) -> None:
    """Accepted intent owns recovery even when a Spotify response is lost.

    Args:
        accepted: Whether the interrupted effect was accepted.
        boundary: Destination append or source removal.
    """
    memory = _memory()
    memory.failure, memory.accepted = boundary, accepted
    reader = TransferReader(["accept"])
    with pytest.raises(RuntimeError, match=f"{boundary} interrupted"):
        await _review(memory, reader)
    recovered = TransferReader()
    result = await _review(memory, recovered)
    assert result.after == 1 and recovered.offered == []
    assert memory.playlists == {"new": [SOURCE], "cellar": [OTHER]}


@pytest.mark.parametrize("accepted", [False, True])
async def test_intent_checkpoint_controls_whether_reconfirmation_is_needed(
    accepted: bool,
) -> None:
    """No destination write can precede successful intent persistence.

    Args:
        accepted: Whether the checkpoint was persisted before losing its response.
    """
    memory = _memory()
    memory.failure, memory.accepted = "save", accepted
    with pytest.raises(RuntimeError, match="save interrupted"):
        await _review(memory, TransferReader(["accept"]))
    assert memory.playlists["new"] == []
    recovered = TransferReader([] if accepted else ["accept"])
    await _review(memory, recovered)
    assert len(recovered.offered) == (0 if accepted else 1)
    assert memory.playlists == {"new": [SOURCE], "cellar": [OTHER]}


@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
async def test_cancellation_checks_guard_prompt_checkpoint_and_removal(
    boundary: int,
) -> None:
    """Cancellation leaves a safe source or destination and a recoverable intent.

    Args:
        boundary: Before prompt, after choice, after checkpoint or after append.
    """
    memory = _memory()
    reader = TransferReader(["accept"], interrupt_at=boundary)
    with pytest.raises(RuntimeError, match="transfer cancelled"):
        await _review(memory, reader)
    assert memory.playlists["cellar"] == [SOURCE, OTHER]
    assert memory.playlists["new"] == ([SOURCE] if boundary == 4 else [])
    run = cast(dict[str, object], memory.stored.get("active_run") or {})
    assert bool(run.get("refill_pending")) == (boundary >= 3)


async def test_preexisting_intent_reconciles_duplicate_even_at_capacity() -> None:
    """Upgrade retains accepted pending authority without a new confirmation."""
    memory = _memory()
    memory.playlists["new"] = [SOURCE]
    memory.stored = {
        "active_run": {"run_id": "run", "refill_pending": {"source": asdict(SOURCE)}}
    }
    reader = TransferReader()
    result = await _review(memory, reader)
    assert result.added == 0 and result.removed_from_cellar == 1
    assert reader.offered == [] and memory.playlists["cellar"] == [OTHER]


@pytest.mark.parametrize("bad", [None, "source", [12], [""]])
async def test_malformed_skipped_progress_is_not_silently_discarded(
    bad: object,
) -> None:
    """Invalid persisted review progress fails before transfer writes.

    Args:
        bad: Unsupported persisted skipped-marker shape.
    """
    memory = _memory()
    memory.stored = {"active_run": {"run_id": "run", "refill_skipped": bad}}
    with pytest.raises(NewWineStateError, match="skipped marker"):
        await _review(memory, TransferReader())
    assert memory.playlists["new"] == []
