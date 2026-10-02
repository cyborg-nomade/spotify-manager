"""Validate seed requests before observing the week or applying listening policies."""

from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.found_art_values import FoundArtStateError
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from spotify_manager.domain.recommendation_seeds import choose_seeds


@dataclass(frozen=True)
class RecommendationSeeds:
    """Validate seed requests and preserve the original clock and diversity errors.

    Args:
        current_week: Resolve the week only after validating and materializing history.
        pool_multiplier: Original per-group candidate pool multiplier.
        max_per_artist: Original artist diversity limit.
    """

    current_week: Callable[[], date]
    pool_multiplier: int = 10
    max_per_artist: int = 2

    def run(
        self, history: Iterable[TrackHistory], count: int, week: date | None
    ) -> tuple[FoundArtSeed, ...]:
        """Select complete weekly seeds or raise the original request/state error.

        Args:
            history: Original ordered history, consumed once after count validation.
            count: Requested number of seeds.
            week: Optional effective listening week.

        Returns:
            Exactly the requested number of seeds.

        Raises:
            FoundArtConfigError: Count is less than one.
            FoundArtStateError: History is empty or lacks enough diverse seeds.
        """
        if count < 1:
            raise FoundArtConfigError("Seed count must be at least 1.")
        tracks = tuple(history)
        if not tracks:
            raise FoundArtStateError(
                "No tracks are available for recommendation seeds."
            )
        active_week = week or self.current_week()
        selected = choose_seeds(
            tracks, count, active_week, self.pool_multiplier, self.max_per_artist
        )
        if len(selected) < count:
            raise FoundArtStateError(
                f"Only {len(selected)} sufficiently diverse seed tracks are "
                f"available; {count} were requested."
            )
        return selected
