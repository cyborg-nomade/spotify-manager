"""Validate Queue seed requests before resolving the original effective week."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from spotify_manager.application.ports.calendar import ListeningCalendar
from spotify_manager.application.queue_values import QueueConfigError
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.queue_seeds import select_seeds
from spotify_manager.domain.queue_values import ArtistHistory
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.domain.recommendation_history import listening_week_start


@dataclass(frozen=True)
class QueueSeeds:
    """Keep original validation/materialization/week order before pure seed selection.

    Args:
        calendar: Original listening-week boundary, called only when needed.
        pool_multiplier: Original per-quota candidate pool multiplier.
    """

    calendar: ListeningCalendar
    pool_multiplier: int = 10

    def select(
        self, history: Iterable[ArtistHistory], count: int, week: date | None
    ) -> tuple[ArtistSeed, ...]:
        """Validate the requested count and available input before resolving the week.

        Args:
            history: Original history facts, possibly a single-use iterable.
            count: Original requested seed count.
            week: Optional original explicit listening week.

        Returns:
            Original ordered weekly seeds.

        Raises:
            QueueConfigError: Original seed count is below one.
            QueueStateError: Original input contains too few history artists.
        """
        if count < 1:
            raise QueueConfigError("Seed count must be at least 1.")
        artists = tuple(history)
        if len(artists) < count:
            raise QueueStateError(
                f"Only {len(artists)} seed artists are available; {count} requested."
            )
        active_week = week or listening_week_start(self.calendar.local_date())
        return select_seeds(artists, count, active_week, self.pool_multiplier)
