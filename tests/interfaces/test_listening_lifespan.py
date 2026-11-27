"""Keep existing job shutdown ahead of potentially slow analytics-cache cleanup."""

from dataclasses import dataclass
from dataclasses import field
from types import TracebackType
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.interfaces.http import jobs


@dataclass
class _ExecutionProbe:
    events: list[str]
    jobs: JobTasks = field(default_factory=JobTasks, init=False)

    async def __aenter__(self) -> _ExecutionProbe:
        self.events.append("execution entered")
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.jobs.close()
        self.events.append("execution closed")


@dataclass
class _ListeningProbe:
    events: list[str]

    async def close(self) -> None:
        self.events.append("listening closed")


async def test_job_runtime_closes_before_waiting_for_listening_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow source read cannot postpone the original job cancellation boundary.

    Args:
        monkeypatch: Scoped concrete runtime/bootstrap replacements.
    """
    events: list[str] = []
    monkeypatch.setattr(jobs, "_hydrate_library_data", AsyncMock())
    monkeypatch.setattr(
        jobs, "ExecutionRuntime", Mock(return_value=_ExecutionProbe(events))
    )
    monkeypatch.setattr(
        jobs, "listening_explorer_runtime", Mock(return_value=_ListeningProbe(events))
    )
    async with jobs._lifespan(FastAPI()):
        events.append("application running")
    assert events == [
        "execution entered",
        "application running",
        "execution closed",
        "listening closed",
    ]
