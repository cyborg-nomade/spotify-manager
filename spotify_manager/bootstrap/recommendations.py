"""Compose recommendation seed selection with the original calendar and limits."""

from collections.abc import Iterable
from datetime import date

from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from spotify_manager.routines import found_art as legacy


def select_seeds(
    history: Iterable[TrackHistory], count: int, week: date | None
) -> tuple[FoundArtSeed, ...]:
    """Bind independent seed selection to the existing routine configuration.

    Args:
        history: Original ordered listening statistics.
        count: Requested seed count.
        week: Optional effective listening week.

    Returns:
        Original selected seeds in group and fallback order.

    Raises:
        FoundArtConfigError: Count is invalid.
        FoundArtStateError: History is empty or insufficiently diverse.
    """
    workflow = RecommendationSeeds(
        legacy.listening_week_start,
        legacy.WEEKLY_SEED_POOL_MULTIPLIER,
        legacy.MAX_SEEDS_PER_ARTIST,
    )
    return workflow.run(history, count, week)
