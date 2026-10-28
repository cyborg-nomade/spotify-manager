"""Bridge original annual namespace acknowledgments and shallow loaded records."""

import asyncio
from dataclasses import dataclass
from typing import cast

from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.core.state.service import StateNamespace
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


@dataclass(frozen=True)
class LegacyAnnualState:
    """Retain original namespace conflict handling without adding record validation.

    Args:
        access: Original complete annual namespace access.
    """

    access: StateNamespace

    async def load(self) -> RetrospectiveState:
        """Read original shallow-validated records without normalizing stored plans.

        Returns:
            Original complete detached namespace, including unknown fields.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_load))
            return await finish_blocking(task)

    def _blocking_load(self) -> RetrospectiveState:
        """Read original shallow-validated records without normalizing stored plans.

        Returns:
            Original complete detached namespace, including unknown fields.
        """
        return cast(RetrospectiveState, self.access.load())

    async def save(self, state: RetrospectiveState, /) -> object:
        """Accept original complete namespace through its existing conflict policy.

        Args:
            state: Original complete changed namespace.

        Returns:
            Original acknowledgment ignored by the annual coordinator.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_save, state))
            return await finish_blocking(task)

    def _blocking_save(self, state: RetrospectiveState, /) -> object:
        """Accept original complete namespace through its existing conflict policy.

        Args:
            state: Original complete changed namespace.

        Returns:
            Original acknowledgment ignored by the annual coordinator.
        """
        return self.access.save(cast(dict[str, object], state))
