"""Keep state transactions serialized without blocking the ASGI event loop."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from spotify_manager import web
from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.infrastructure.genre_models import GenreRevealState
from spotify_manager.infrastructure.genre_models import GenreRevealStateUpdate
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.handlers import releases
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateRestoreRequest,
)
from spotify_manager.interfaces.http.models.releases import ReleaseCheckStateSnapshot
from spotify_manager.routines import genre_reveal


async def test_genre_reads_wait_for_the_invocations_state_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue a state read while the event loop continues delivering other work.

    Args:
        monkeypatch: Isolate the original complete synchronous state read.
    """
    state = GenreRevealState()
    read = Mock(return_value=state)
    monkeypatch.setattr(genre_reveal, "load_genre_reveal_state", read)
    async with ExecutionRuntime() as runtime:
        await runtime.genre_state_lock.acquire()
        pending = asyncio.create_task(web.get_genre_reveal_state())
        try:
            await asyncio.sleep(0)
            assert not pending.done()
            read.assert_not_called()
        finally:
            runtime.genre_state_lock.release()
        assert await pending == state
    read.assert_called_once()


async def test_cancelling_a_queued_genre_write_leaves_the_owner_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel a waiting writer without entering persistence or releasing its owner.

    Args:
        monkeypatch: Isolate the native complete state replacement.
    """
    save = AsyncMock()
    monkeypatch.setattr(genre_reveal, "async_save_genre_reveal_state", save)
    async with ExecutionRuntime() as runtime:
        await runtime.genre_state_lock.acquire()
        pending = asyncio.create_task(
            web.put_genre_reveal_state(GenreRevealStateUpdate())
        )
        await asyncio.sleep(0)
        pending.cancel()
        try:
            await _expect_cancelled(pending)
            assert runtime.genre_state_lock.locked()
            save.assert_not_awaited()
        finally:
            runtime.genre_state_lock.release()


async def _expect_cancelled(task: asyncio.Task[GenreRevealState]) -> None:
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_release_restore_waits_without_locking_the_job_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue a restore while ordinary registry access and the loop keep progressing.

    Args:
        monkeypatch: Isolate the exact complete restore transaction.
    """
    snapshot = ReleaseCheckStateSnapshot(updated_at=None, fingerprint="original")
    restore = Mock(return_value=snapshot)
    monkeypatch.setattr(releases, "_restore_state_locked", restore)
    request = ReleaseCheckStateRestoreRequest(
        expected_server_fingerprint="original", state={}
    )
    async with ExecutionRuntime() as runtime:
        await runtime.release_state_lock.acquire()
        pending = asyncio.create_task(releases.cmd_restore_release_check_state(request))
        try:
            await asyncio.sleep(0)
            assert not pending.done()
            restore.assert_not_called()
            assert jobs._blast_jobs_lock.acquire(blocking=False)
            jobs._blast_jobs_lock.release()
        finally:
            runtime.release_state_lock.release()
        assert await pending == snapshot
    restore.assert_called_once_with(request)


async def test_release_submission_waits_for_an_inflight_state_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a new release job from reading state until its restore has finished.

    Args:
        monkeypatch: Isolate configured references and the named job submission.
    """
    configuration = Mock(
        wine_cellar_playlist="cellar",
        new_vintage_playlist="vintage",
        lastfm_api_key="key",
        lastfm_username="listener",
    )
    snapshot = jobs.BlastJobResult(job_id="new-release", dry_run=True)
    start = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(jobs, "Settings", Mock(return_value=configuration))
    monkeypatch.setattr(jobs, "start_release_check_job", start)
    async with ExecutionRuntime() as runtime:
        await runtime.release_state_lock.acquire()
        pending = asyncio.create_task(releases.cmd_check_new_releases(Mock(), True))
        try:
            await asyncio.sleep(0)
            assert not pending.done()
            start.assert_not_awaited()
        finally:
            runtime.release_state_lock.release()
        assert await pending == snapshot
    start.assert_awaited_once()
