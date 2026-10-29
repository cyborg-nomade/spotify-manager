"""Verify pooled resources remain owned by their invocation and original loop."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest

from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.bootstrap.execution import current_execution
from spotify_manager.bootstrap.spotify_async import AsyncSpotifyRuntime
from spotify_manager.client.events import SPOTIFY_MESSAGES
from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.infrastructure.async_signal import AsyncSignal
from spotify_manager.infrastructure.spotify_async.oauth import OAuthProvisioner
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.infrastructure.spotify_async.transport import (
    NativeSpotifyTransport,
)
from spotify_manager.settings import Settings
from tests.async_execution.runtime_memory import ConstructionGate
from tests.async_execution.runtime_memory import InterruptedWorker
from tests.async_execution.runtime_memory import ObservedEvents
from tests.spotify_async.memory import OutputMemory
from tests.spotify_async.memory import TokenMemory
from tests.spotify_async.memory import transport_memory


async def test_invocation_reuses_clients_and_closes_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Share the HTTP pool and refresh locks while retaining original retry scopes.

    Args:
        monkeypatch: Scoped synchronous OAuth source substitution.
    """
    token = TokenMemory()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(token,)))
    async with ExecutionRuntime() as runtime:
        assert current_execution() is runtime
        standard = await runtime.client()
        assert standard is await runtime.client()
        analysis = await runtime.client("analysis")
        assert analysis is await runtime.client("analysis")
        left, right = standard.transport, analysis.transport
        assert isinstance(left, NativeSpotifyTransport)
        assert isinstance(right, NativeSpotifyTransport)
        assert left.http is right.http
        assert left.credentials.entries is right.credentials.entries
        assert left.credentials is not right.credentials
        assert right.profile == RetryProfile(0, 0, (999,))
        await right.aclose()
        assert not left.http.is_closed and not token.closed
    assert left.http.is_closed and token.closed
    with pytest.raises(RuntimeError, match="owning runtime"):
        current_execution()


async def test_shutdown_waits_for_inflight_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close resources created by an already admitted construction during shutdown.

    Args:
        monkeypatch: Scoped construction and OAuth source substitutions.
    """
    token, gate = TokenMemory(), ConstructionGate()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(token,)))
    monkeypatch.setattr(
        ExecutionRuntime, "_open_owner", AsyncMock(side_effect=gate.open)
    )
    async with ExecutionRuntime() as runtime:
        opening = asyncio.create_task(runtime.client())
        await gate.entered.wait()
        closing = asyncio.create_task(runtime._close())
        await asyncio.sleep(0)
        assert not closing.done()
        gate.release.set()
        client = await opening
        await closing
        assert isinstance(client.transport, NativeSpotifyTransport)
        assert client.transport.http.is_closed and token.closed
        with pytest.raises(RuntimeError, match="not active"):
            await runtime.client()


async def test_runtime_rejects_client_acquisition_on_another_loop() -> None:
    """Reject cross-loop use before configuration or SDK construction starts."""
    async with ExecutionRuntime() as runtime:
        with pytest.raises(RuntimeError, match="another event loop"):
            await asyncio.to_thread(asyncio.run, runtime.client())


async def test_retry_profiles_reject_closed_or_unentered_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep borrowed views within their native owner's active resource lifetime.

    Args:
        monkeypatch: Scoped synchronous OAuth source substitution.
    """
    token = TokenMemory()
    monkeypatch.setattr(OAuthProvisioner, "open_sources", Mock(return_value=(token,)))
    runtime = AsyncSpotifyRuntime(Settings())
    with pytest.raises(RuntimeError, match="not been entered"):
        runtime.profile(RetryProfile())
    async with runtime:
        view = runtime.profile(RetryProfile())
    with pytest.raises(RuntimeError, match="not been entered"):
        runtime.profile(RetryProfile())
    with pytest.raises(RuntimeError, match="closed"):
        await view.current_user()


async def test_shared_native_client_keeps_job_diagnostics_separate() -> None:
    """Restore task-local observers after overlapping subscriptions."""
    memory = transport_memory()
    from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify

    client = AsyncSpotify(memory.transport)
    left, right = OutputMemory(), OutputMemory()
    barrier = asyncio.Barrier(2)
    try:
        await asyncio.gather(
            ObservedEvents(client, barrier, left, "left").run(),
            ObservedEvents(client, barrier, right, "right").run(),
        )
        assert left.lines == ["left"] and right.lines == ["right"]
        assert SPOTIFY_MESSAGES.get() is None
    finally:
        await memory.transport.aclose()


async def test_worker_process_control_does_not_terminate_the_web_loop() -> None:
    """Retain worker-local termination while allowing lifespan cleanup to finish."""
    tasks = JobTasks()
    tasks.start(InterruptedWorker().run(), AsyncSignal(), "interrupted")
    await tasks.close()
    await asyncio.sleep(0)
