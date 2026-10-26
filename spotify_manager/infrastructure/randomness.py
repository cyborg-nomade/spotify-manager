"""Read Random.org responses through named external resources."""

from spotify_manager.application.historical_values import RandomIndexSet


class RandomOrgIndexes:
    """Own the original Random.org index request."""

    def sample(self, population: int, count: int) -> RandomIndexSet:
        """Read the original external random indexes.

        Args:
            population: Original eligible population size.
            count: Original requested count.

        Returns:
            Original complete random response.
        """
        from spotify_manager.routines.blast_from_past import fetch_random_indexes

        return fetch_random_indexes(population, count)


RANDOM_INDEXES = RandomOrgIndexes()
