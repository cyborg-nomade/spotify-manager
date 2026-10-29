"""Read Random.org responses through named external resources."""

import asyncio

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


class RandomOrgIndexes:
    """Own the original Random.org index request."""

    async def sample(self, population: int, count: int) -> RandomIndexSet:
        """Read the original external random indexes.

        Args:
            population: Original eligible population size.
            count: Original requested count.

        Returns:
            Original complete random response.
        """
        from spotify_manager.routines.blast_from_past import (
            fetch_random_indexes as _fetch_random_indexes,
        )

        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_fetch_random_indexes, population, count)
            )
            return await finish_blocking(file_operation)


RANDOM_INDEXES = RandomOrgIndexes()
