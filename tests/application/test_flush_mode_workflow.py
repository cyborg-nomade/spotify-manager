"""Verify real persistence, check failures and concurrent operator decisions."""

import asyncio
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.application.flush_mode import FlushModeBlockedError
from spotify_manager.application.flush_mode import check_flush_mode
from spotify_manager.application.flush_mode import new_wine_no_discovery
from spotify_manager.application.flush_mode import require_routine_start
from spotify_manager.domain.flush_mode import BLOCKED_COMMANDS
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts
from tests.support.flush_mode import CheckClock
from tests.support.flush_mode import CountObservation
from tests.support.flush_mode import stored_mode


CLOCK = CheckClock(datetime(2026, 11, 9, tzinfo=UTC))


@pytest.mark.parametrize("command", sorted(BLOCKED_COMMANDS))
def test_every_restricted_command_rejects_active_mode(command: str) -> None:
    """Dry-run and resumed invocation identities share the same admission rule.

    Args:
        command: Canonical restricted routine identity.
    """
    with pytest.raises(FlushModeBlockedError, match="Flush Mode is active"):
        require_routine_start(command, FlushState(control="on"))
    require_routine_start(command, FlushState(control="off", automatic_active=True))
    require_routine_start("daily_mind_radio", FlushState(control="on"))


def test_wine_policy_retains_force_identity() -> None:
    """Only active Flush Mode overrides a saved false mode on resume."""
    forced = new_wine_no_discovery(False, FlushState(control="on"))
    assert forced.no_discovery and forced.forced
    requested = new_wine_no_discovery(True, FlushState())
    assert requested.no_discovery and not requested.forced
    assert not new_wine_no_discovery(False, FlushState()).no_discovery


async def test_check_failure_retains_decision_counts_and_override(
    tmp_path: Path,
) -> None:
    """A failed check cannot clear active mode or discard successful observations.

    Args:
        tmp_path: Independent state directory.
    """
    store = stored_mode(tmp_path / "state.json")
    before = await check_flush_mode(
        store, CountObservation(QueueCounts(2400, 0)), CLOCK
    )
    assert before.active and before.checked_at
    await store.control("off")
    failed = await check_flush_mode(
        store, CountObservation(QueueCounts(0, 0), "offline"), CLOCK
    )
    assert failed.counts == before.counts and failed.checked_at == before.checked_at
    assert failed.automatic_active and not failed.active and failed.error == "offline"
    assert (await store.control("automatic")).active


async def test_override_during_check_survives_restart(tmp_path: Path) -> None:
    """The live count read does not hold or overwrite operator control.

    Args:
        tmp_path: Independent state directory.
    """
    path = tmp_path / "state.json"
    store = stored_mode(path)
    entered, release = asyncio.Event(), asyncio.Event()
    counts = CountObservation(QueueCounts(2400, 1200), entered=entered, release=release)
    task = asyncio.create_task(check_flush_mode(store, counts, CLOCK))
    await entered.wait()
    await store.control("off")
    release.set()
    result = await task
    assert result.control == "off" and not result.active and result.automatic_active
    restarted = await stored_mode(path).load()
    assert restarted == result
    assert (await store.control("automatic")).active


@pytest.mark.parametrize("error", [None, "offline"])
async def test_older_check_cannot_replace_newer_observations(
    tmp_path: Path, error: str | None
) -> None:
    """Out-of-order completion retains the newer successful check.

    Args:
        tmp_path: Independent state directory.
        error: Optional failure of the older count read.
    """
    store = stored_mode(tmp_path / "state.json")
    entered, release = asyncio.Event(), asyncio.Event()
    old = CountObservation(
        QueueCounts(2400, 0), error=error, entered=entered, release=release
    )
    task = asyncio.create_task(check_flush_mode(store, old, CLOCK))
    await entered.wait()
    later = CheckClock(datetime(2026, 11, 10, tzinfo=UTC))
    expected = await check_flush_mode(store, CountObservation(QueueCounts(5, 6)), later)
    release.set()
    assert await task == expected
    assert not expected.active and expected.counts == QueueCounts(5, 6)
