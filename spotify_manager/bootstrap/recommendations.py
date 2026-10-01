"""Compose recommendation seed selection with the original calendar and limits."""

from collections.abc import Iterable
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from spotify_manager.infrastructure.legacy.recommendations import LegacyNeighborhoods
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


def _generated_at(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def gather_candidates(
    lastfm: legacy.LastFmReader,
    seeds: tuple[FoundArtSeed, ...],
    heard: set[TrackKey],
    cache_path: Path,
    log_path: Path | None,
    week: date | None,
    pool_size: int,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> tuple[FoundArtCandidate, ...]:
    """Compose neighborhood gathering with original storage and calendar helpers.

    Args:
        lastfm: Caller-owned Last.fm reader.
        seeds: Ordered weighted seeds.
        heard: Original heard-track identities.
        cache_path: Original cache destination.
        log_path: Optional prior-addition log.
        week: Optional effective listening week.
        pool_size: Original positive candidate pool limit.
        now: Optional effective UTC time.
        progress: Optional per-seed presenter.

    Returns:
        Original ranked unheard candidates.

    Raises:
        FoundArtConfigError: Pool size is invalid.
        FoundArtStateError: Cache or prior-addition data is invalid.
    """
    observations = LegacyNeighborhoods(lastfm, cache_path, log_path)
    workflow = CandidateGathering(
        observations,
        observations.neighbors,
        partial(_generated_at, now),
        legacy.listening_week_start,
        partial(_progress, progress),
    )
    return workflow.run(seeds, heard, week, pool_size)
