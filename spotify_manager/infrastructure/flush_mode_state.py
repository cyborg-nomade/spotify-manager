"""Merge Flush Mode observations and overrides through central namespace CAS."""

import asyncio
from dataclasses import dataclass

from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.flush_mode import FlushChange
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.flush_mode_schema import FlushModeDefinition
from spotify_manager.infrastructure.flush_mode_schema import decode_flush_state
from spotify_manager.infrastructure.flush_mode_schema import encode_flush_state
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class FlushModeState:
    """Own conflict-aware persistence, leaving unrelated namespaces untouched.

    Args:
        service: Existing central state service.
    """

    service: StateService

    def load(self) -> FlushState:
        """Read validated state without creating a namespace on disk.

        Returns:
            Current state or unobserved defaults.
        """
        namespace = self.service.namespace("flush_mode", FlushModeDefinition())
        return decode_flush_state(namespace.load())

    def change(self, update: FlushChange) -> FlushState:
        """Retry conflicts by reapplying owned fields to fresh state.

        Args:
            update: Explicit control, success or failure change.

        Returns:
            Committed state preserving concurrent manual overrides and observations.

        Raises:
            StateConflictError: Repeated concurrent writes prevent publication.
            StateError: Reading, validation or publication fails.
        """
        for _attempt in range(5):
            try:
                return self._attempt(update)
            except StateConflictError:
                continue
        raise StateConflictError("Flush Mode changed repeatedly. Try again.")

    def _attempt(self, update: FlushChange) -> FlushState:
        namespace = self.service.namespace("flush_mode", FlushModeDefinition())
        before = decode_flush_state(namespace.load())
        after = update.apply(before)
        if after == before:
            return before
        namespace.save(encode_flush_state(after), message="Update Flush Mode")
        return after


@dataclass(frozen=True)
class AsyncFlushModeState:
    """Finish complete state operations off the event loop before releasing files.

    Args:
        source: Synchronous, conflict-aware namespace owner.
    """

    source: FlushModeState

    async def load(self) -> FlushState:
        """Read state off the event loop.

        Returns:
            Validated control and observations.
        """
        # asyncio.to_thread requires a callable for this blocking storage operation.
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.load))
            return await finish_blocking(task)

    async def control(self, value: FlushControl) -> FlushState:
        """Persist only the operator override.

        Args:
            value: New persistent control selection.

        Returns:
            Committed state preserving current observations.
        """
        return await self._change(FlushChange(control=value))

    async def observed(
        self, counts: QueueCounts, started: str, completed: str
    ) -> FlushState:
        """Merge successful observations while preserving the latest override.

        Args:
            counts: Both complete live counts.
            started: UTC check start used for ordering.
            completed: UTC successful completion.

        Returns:
            Latest committed control and automatic decision.
        """
        return await self._change(
            FlushChange(counts=counts, started=started, completed=completed)
        )

    async def failed(self, started: str, detail: str) -> FlushState:
        """Record stale observations without changing the effective decision.

        Args:
            started: UTC failed-check start used for ordering.
            detail: Safe operator-facing failure reason.

        Returns:
            Latest state retaining previous successful counts and decision.
        """
        return await self._change(FlushChange(started=started, error=detail))

    async def _change(self, update: FlushChange) -> FlushState:
        # asyncio.to_thread is the framework's blocking-operation submission API.
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.change, update))
            return await finish_blocking(task)
