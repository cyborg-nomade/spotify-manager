"""Named JSON Lines audit storage for Requeue outcomes."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.requeue_result import RequeueForADreamSummary
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class RequeueAudit:
    """Own the original audit file destination.

    Args:
        path: Explicit audit destination.
    """

    path: Path

    async def write(self, result: RequeueForADreamSummary) -> None:
        """Accept a complete outcome with the original bytes and error semantics.

        Args:
            result: Complete routine outcome.
        """
        from spotify_manager.routines.requeue_for_a_dream import _append_log

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_append_log, result, self.path)
            )
            await finish_blocking(file_operation)
