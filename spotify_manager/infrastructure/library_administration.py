"""Await complete canonical artifact operations at the persistence boundary."""

import asyncio
from dataclasses import dataclass

from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.sync_compat import LegacyControl
from spotify_manager.infrastructure.sync_compat import finish_legacy


@dataclass(frozen=True)
class LibraryAdministration:
    """Keep operator decisions and ordered iteration in their interface owner.

    Args:
        source: Existing caller-owned artifact service.
    """

    source: LibraryDataService

    async def statuses(self) -> tuple[ArtifactStatus, ...]:
        """Read the original complete remote and local synchronization status.

        Returns:
            Original ordered artifact statuses.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._statuses))
            return await finish_legacy(task)

    def _statuses(self) -> tuple[ArtifactStatus, ...]:
        with LegacyControl():
            return self.source.statuses()

    async def hydrate(self, name: ArtifactName) -> ArtifactStatus:
        """Finish one original artifact hydration before advancing the caller.

        Args:
            name: Original selected artifact.

        Returns:
            Original artifact status after hydration.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._hydrate, name))
            return await finish_legacy(task)

    def _hydrate(self, name: ArtifactName) -> ArtifactStatus:
        with LegacyControl():
            return self.source.hydrate(name)

    async def publish(self, name: ArtifactName) -> LibraryDataSnapshot:
        """Complete one accepted publication before the interface advances.

        Args:
            name: Original selected artifact.

        Returns:
            Accepted artifact manifest and revision.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._publish, name))
            return await finish_legacy(task)

    def _publish(self, name: ArtifactName) -> LibraryDataSnapshot:
        with LegacyControl():
            return self.source.publish(name, source="manual CLI publication")
