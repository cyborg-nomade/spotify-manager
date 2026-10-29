"""Verify signal delivery and CLI retry interruption with controlled task ordering."""

import asyncio

import pytest

from spotify_manager.infrastructure.async_signal import AsyncSignal
from spotify_manager.infrastructure.cli_cancellation import INVOCATION_WAIT
from spotify_manager.infrastructure.cli_cancellation import CliCancellation
from spotify_manager.infrastructure.cli_cancellation import CliInterruptedError


async def test_signal_state_is_immediate_after_loop_binding() -> None:
    """Preserve synchronous event observations while scheduling async wakeups."""
    signal = AsyncSignal()
    assert not await signal.wait(0)
    signal.set()
    assert signal.is_set()
    assert await signal.wait(0)
    signal.clear()
    assert not signal.is_set()
    await asyncio.sleep(0)
    assert not await signal.wait(0)


async def test_clear_discards_a_queued_wakeup_from_a_consumed_choice() -> None:
    """Do not let an earlier submitted choice wake the following prompt."""
    signal = AsyncSignal()
    assert not await signal.wait(0)
    signal.set()
    signal.clear()
    await asyncio.sleep(0)
    assert not await signal.wait(0)
    signal.set()
    assert await signal.wait()


async def test_http_delivery_thread_wakes_the_loop_owned_signal() -> None:
    """Accept a synchronous endpoint's notification without blocking its worker."""
    signal = AsyncSignal()
    assert not await signal.wait(0)
    waiting = asyncio.create_task(signal.wait())
    await asyncio.to_thread(signal.set)
    assert await waiting
    assert signal.is_set()


async def test_signal_rejects_reuse_on_another_event_loop() -> None:
    """Reject loop ownership mistakes instead of retaining stale waiter state."""
    signal = AsyncSignal()
    assert not await signal.wait(0)
    with pytest.raises(RuntimeError, match="another event loop"):
        await asyncio.to_thread(asyncio.run, signal.wait(0))


async def test_cli_interruption_wakes_an_outstanding_retry() -> None:
    """End a CLI retry delay without changing ordinary web retry waits."""
    with CliCancellation() as cancellation:
        waiting = asyncio.create_task(INVOCATION_WAIT.sleep(3600))
        await asyncio.sleep(0)
        cancellation.request()
        with pytest.raises(CliInterruptedError):
            await waiting
    await INVOCATION_WAIT.sleep(0)


async def test_already_interrupted_cli_does_not_start_another_wait() -> None:
    """Observe a pending stop even when the requested retry delay is zero."""
    with CliCancellation() as cancellation:
        cancellation.request()
        with pytest.raises(CliInterruptedError):
            await INVOCATION_WAIT.sleep(0)
