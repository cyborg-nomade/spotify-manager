"""Await complete shared-state reads and writes for the administrative interface."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy


@dataclass(frozen=True)
class StateAdministration:
    """Bound one complete persistence operation without offloading UI execution.

    Args:
        source: Existing caller-owned shared-state service.
    """

    source: StateService

    async def snapshot(self) -> StateSnapshot:
        """Read current state and its revision.

        Returns:
            Original detached state snapshot.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._snapshot))
            return await finish_legacy(task)

    def _snapshot(self) -> StateSnapshot:
        with LegacyControl():
            return self.source.snapshot()

    async def export(self, destination: Path) -> StateSnapshot:
        """Complete the original snapshot export as one persistence operation.

        Args:
            destination: Original caller-selected JSON path.

        Returns:
            Exported state and revision.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._export, destination))
            return await finish_legacy(task)

    def _export(self, destination: Path) -> StateSnapshot:
        with LegacyControl():
            return self.source.export(destination)

    async def replace(
        self, document: dict[str, Any], revision: str, message: str
    ) -> StateSnapshot:
        """Finish the original compare-and-swap write before returning.

        Args:
            document: Original permissive external state document.
            revision: Revision observed before operator approval.
            message: Original publication message.

        Returns:
            Accepted state and its new revision.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self._replace, document, revision, message)
            )
            return await finish_legacy(task)

    def _replace(
        self, document: dict[str, Any], revision: str, message: str
    ) -> StateSnapshot:
        with LegacyControl():
            return self.source.replace(
                document, expected_revision=revision, message=message
            )
