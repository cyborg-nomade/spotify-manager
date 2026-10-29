"""Protect write acceptance, restart recovery and worker/task cleanup boundaries."""

import asyncio
import inspect

import pytest

from spotify_manager.application.requeue import flush_requeue
from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.infrastructure.async_signal import AsyncSignal
from spotify_manager.infrastructure.async_state import AsyncRoutineState
from spotify_manager.infrastructure.async_work import BlockingBinding
from tests.application.test_requeue import SOURCE
from tests.async_execution.memory import BarrierRequeue
from tests.async_execution.memory import BlockingState
from tests.async_execution.memory import CheckedPlaylists
from tests.async_execution.memory import RequeueJob
from tests.async_execution.memory import StopBoundary


async def test_shutdown_retains_accepted_write_and_restart_recovery() -> None:
    """Drain an accepted write and recover without duplicating its effects."""
    signal = AsyncSignal()
    memory = BarrierRequeue(playlist=[SOURCE])
    playlists = CheckedPlaylists(memory, StopBoundary(signal))
    job = RequeueJob(playlists)
    tasks = JobTasks()
    tasks.start(job.run(), signal, "requeue")
    await memory.barrier.entered.wait()
    closing = asyncio.create_task(tasks.close())
    await signal.wait()
    assert job.summary is None and not job.stopped
    memory.barrier.release.set()
    await closing
    assert job.stopped and not memory.audits
    assert [item.spotify_id for item in memory.playlist] == ["source", "target"]
    signal.clear()
    summary = await flush_requeue(playlists.dependencies(), "queue")
    assert summary.target_already_present
    assert [item.spotify_id for item in memory.playlist] == ["target"]
    assert len(memory.audits) == 1
    assert sum(event[0] == "append" for event in memory.events) == 1


async def test_cancelled_shutdown_still_drains_accepted_write() -> None:
    """Keep shutdown ownership even if the caller receives repeated cancellation."""
    signal = AsyncSignal()
    memory = BarrierRequeue(playlist=[SOURCE])
    job = RequeueJob(CheckedPlaylists(memory, StopBoundary(signal)))
    tasks = JobTasks()
    tasks.start(job.run(), signal, "requeue")
    await memory.barrier.entered.wait()
    closing = asyncio.create_task(tasks.close())
    await signal.wait()
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    memory.barrier.release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert job.stopped
    assert [item.spotify_id for item in memory.playlist] == ["source", "target"]
    await tasks.close()


async def test_cancelled_file_write_retains_capacity_until_commit() -> None:
    """Allow another read only after a cancelled synchronous write has finished."""
    source = BlockingState()
    access = AsyncRoutineState(source)
    with BlockingBinding(asyncio.Semaphore(1)):
        writing = asyncio.create_task(access.save({"version": 1}))
        await asyncio.to_thread(source.entered.wait)
        reading = asyncio.create_task(access.load())
        writing.cancel()
        await asyncio.sleep(0)
        try:
            assert source.events == ["write-started"]
        finally:
            source.release.set()
        with pytest.raises(asyncio.CancelledError):
            await writing
        assert await reading == {"version": 1}
    assert source.events == ["write-started", "write-accepted", "read"]


async def test_shutdown_rejects_and_closes_new_coroutines() -> None:
    """Reject new work after shutdown without leaking its unawaited coroutine."""
    tasks = JobTasks()
    await tasks.close()
    job = RequeueJob(CheckedPlaylists(BarrierRequeue(), StopBoundary(AsyncSignal())))
    operation = job.run()
    with pytest.raises(RuntimeError, match="shutting down"):
        tasks.start(operation, job.playlists.stop.signal, "late")
    assert inspect.iscoroutine(operation)
    assert inspect.getcoroutinestate(operation) == inspect.CORO_CLOSED
