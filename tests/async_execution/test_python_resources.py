"""Exercise caller-owned resource boundaries, loop ownership and admitted I/O."""

import asyncio
import importlib
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from threading import Event
from threading import get_ident
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock

import pytest

from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.infrastructure.python_compat.runtime import PythonWait


@dataclass(frozen=True)
class ResourceCase:
    """Retain the original caller method names and representative arguments.

    Args:
        module: Concrete compatibility module.
        name: Named resource adapter.
        method: Original external method.
        arguments: Distinct positional observations.
        keywords: Original explicit query or page bounds.
    """

    module: str
    name: str
    method: str
    arguments: tuple[object, ...]
    keywords: dict[str, object]

    def resource(self, source: object) -> object:
        """Construct the resource through this parameterized external API inventory.

        Args:
            source: Caller-owned mock with original resource behavior.

        Returns:
            The selected concrete compatibility adapter.
        """
        module = importlib.import_module(
            "spotify_manager.infrastructure.python_compat." + self.module
        )
        return cast(object, getattr(module, self.name)(source))

    def invoke(self, resource: object) -> Coroutine[object, object, object]:
        """Call the inventoried method with the original argument shape.

        Args:
            resource: Concrete compatibility adapter.

        Returns:
            Already selected resource I/O, without invoking an application stage.
        """
        return cast(
            Coroutine[object, object, object],
            getattr(resource, self.method)(*self.arguments, **self.keywords),
        )


def _cases() -> list[ResourceCase]:
    path = Path(__file__).with_name("fixtures") / "python_resource_calls.json"
    rows = cast(list[dict[str, object]], json.loads(path.read_text()))
    cases = []
    for row in rows:
        cases.append(
            ResourceCase(
                str(row["module"]),
                str(row["name"]),
                str(row["method"]),
                tuple(cast(list[object], row["arguments"])),
                cast(dict[str, object], row["keywords"]),
            )
        )
    return cases


CASES = _cases()


@dataclass
class BlockingResource:
    """Control an admitted synchronous interaction without using a live service.

    Args:
        result: Original response object, including invalid caller values.
        entered: Worker entry barrier.
        release: Completion barrier.
        completed: Whether concrete I/O finished.
        worker: Original executing thread identity.
    """

    result: object
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    completed: bool = False
    worker: int | None = None

    def read(self, *args: object, **kwargs: object) -> object:
        """Complete only after the caller releases the accepted I/O boundary.

        Args:
            args: Original positional request observations.
            kwargs: Original keyword request observations.

        Returns:
            The caller's unmodified response object.
        """
        self.worker = get_ident()
        self.entered.set()
        assert self.release.wait(5), "Accepted resource I/O was not released."
        self.completed = True
        return self.result


@dataclass(frozen=True)
class NativeResource:
    """Assert an existing async resource executes on its caller's event loop.

    Args:
        loop: Caller-owned event loop.
        result: Original async result.
    """

    loop: asyncio.AbstractEventLoop
    result: object

    async def read(self, *args: object, **kwargs: object) -> object:
        """Observe original async resource execution after its method is resolved.

        Args:
            args: Original positional observations.
            kwargs: Original keyword observations.

        Returns:
            Original response without interpretation.
        """
        assert asyncio.get_running_loop() is self.loop
        return self.result


@pytest.mark.parametrize("case", CASES)
async def test_sync_resource_retains_truthiness_arguments_and_result(
    case: ResourceCase,
) -> None:
    """Keep caller choices intact while moving their blocking I/O off the loop.

    Args:
        case: Original external resource contract.
    """
    probe = BlockingResource(object())
    probe.release.set()
    source = MagicMock()
    source.__bool__.return_value = False
    observed = Mock(side_effect=probe.read)
    setattr(source, case.method, observed)
    resource = case.resource(source)
    assert source.__bool__.call_count == 0
    assert not bool(resource)
    assert await case.invoke(resource) is probe.result
    observed.assert_called_once_with(*case.arguments, **case.keywords)
    assert probe.completed and probe.worker != get_ident()
    source.__bool__.assert_called_once_with()


@pytest.mark.parametrize("case", CASES)
async def test_existing_async_resource_stays_on_its_original_loop(
    case: ResourceCase,
) -> None:
    """Resolve a caller's async resource without running its body in a worker loop.

    Args:
        case: Original external resource contract.
    """
    source = MagicMock()
    probe = NativeResource(asyncio.get_running_loop(), object())
    observed = AsyncMock(side_effect=probe.read)
    setattr(source, case.method, observed)
    result = await case.invoke(case.resource(source))
    assert result is probe.result
    observed.assert_awaited_once_with(*case.arguments, **case.keywords)


@pytest.mark.parametrize("case", CASES)
async def test_cancellation_drains_an_already_admitted_resource_call(
    case: ResourceCase,
) -> None:
    """Keep I/O and worker capacity owned until an accepted operation finishes.

    Args:
        case: Original external resource contract.
    """
    probe = BlockingResource(object())
    source = MagicMock()
    setattr(source, case.method, Mock(side_effect=probe.read))
    async with ExecutionRuntime():
        task = asyncio.create_task(case.invoke(case.resource(source)))
        try:
            assert await asyncio.to_thread(probe.entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not probe.completed
        finally:
            probe.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert probe.completed


async def test_cancelled_resolution_closes_an_unstarted_native_resource() -> None:
    """Dispose of an unstarted coroutine returned while its SDK worker was draining."""
    native = NativeResource(asyncio.get_running_loop(), object()).read()
    probe = BlockingResource(native)
    source = MagicMock()
    source.sleep.side_effect = probe.read
    task = asyncio.create_task(PythonWait(source).sleep(1))
    try:
        assert await asyncio.to_thread(probe.entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        probe.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inspect.getcoroutinestate(native) == inspect.CORO_CLOSED
