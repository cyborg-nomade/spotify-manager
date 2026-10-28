"""Await complete synchronous namespace operations without splitting their writes."""

import asyncio
from dataclasses import dataclass
from typing import Any

from spotify_manager.application.ports.state import BlockingRoutineState
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class AsyncRoutineState:
    """Own one namespace's async boundary while retaining its complete JSON format.

    Args:
        source: Existing conflict-aware namespace or explicit legacy file owner.
    """

    source: BlockingRoutineState

    async def load(self) -> dict[str, Any]:
        """Read and validate a detached namespace through its original store.

        Returns:
            Complete versioned namespace, including retained unknown JSON fields.

        Raises:
            StateError: Original read or validation failure.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.load))
            return await finish_blocking(task)

    async def save(
        self, value: dict[str, Any], *, message: str | None = None
    ) -> object:
        """Finish a conflict-aware checkpoint before releasing worker capacity.

        Args:
            value: Complete original namespace payload.
            message: Original optional commit description.

        Returns:
            Original store acknowledgment.

        Raises:
            StateError: Original validation, conflict or persistence failure.
        """
        async with blocking_capacity():
            if message is None:
                task = asyncio.create_task(asyncio.to_thread(self.source.save, value))
            else:
                task = asyncio.create_task(
                    asyncio.to_thread(self.source.save, value, message=message)
                )
            result = await finish_blocking(task)
        check_cli_interruption()
        return result
