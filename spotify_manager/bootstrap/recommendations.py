"""Compose recommendation seed selection with the original calendar and limits."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_resolution import (
    RecommendationResolution,
)
from spotify_manager.application.recommendation_run import RecommendationRun
from spotify_manager.application.recommendation_run import RecommendationStages
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.infrastructure.legacy.recommendation_matches import (
    LegacyRecommendationMatches,
)
from spotify_manager.infrastructure.legacy.recommendations import LegacyNeighborhoods
from spotify_manager.infrastructure.legacy.recommendations import (
    LegacyRecommendationRun,
)
from spotify_manager.routines import found_art as legacy


def recommendation_seeds() -> RecommendationSeeds:
    """Construct the invocation dependencies without executing the use case.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar

    workflow = RecommendationSeeds(
        BerlinCalendar(),
        legacy.WEEKLY_SEED_POOL_MULTIPLIER,
        legacy.MAX_SEEDS_PER_ARTIST,
    )
    return workflow


def _generated_at(now: datetime | None) -> datetime:
    return (now or legacy.datetime.now(UTC)).astimezone(UTC)


def candidate_gathering(
    lastfm: legacy.LastFmReader,
    cache_path: Path,
    log_path: Path | None,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> CandidateGathering:
    """Construct the invocation dependencies without executing the use case.

    Args:
        lastfm: Caller-owned Last.fm reader.
        cache_path: Original cache destination.
        log_path: Optional prior-addition log.
        now: Optional effective UTC time.
        progress: Optional per-seed presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar

    observations = LegacyNeighborhoods(lastfm, cache_path, log_path)
    workflow = CandidateGathering(
        observations,
        RecommendationClock(now),
        BerlinCalendar(),
        OptionalMessages(progress),
    )
    return workflow


def recommendation_resolution(
    sp: Spotify, progress: legacy.ProgressCallback | None
) -> RecommendationResolution:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        progress: Optional original progress presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    workflow = RecommendationResolution(
        LegacyRecommendationMatches(sp),
        OptionalMessages(progress),
        legacy.SPOTIFY_RESOLUTION_BATCH_SIZE,
        legacy.SPOTIFY_CANDIDATE_MULTIPLIER,
    )
    return workflow


def recommendation_run(
    sp: Spotify,
    lastfm: legacy.LastFmReader,
    playlist_id: str,
    export_path: Path,
    recent_path: Path,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> RecommendationRun:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        lastfm: Caller-owned history and neighborhood source.
        playlist_id: Original destination.
        export_path: Canonical export destination.
        recent_path: Legacy history delta destination.
        cache_path: Neighborhood cache destination.
        log_path: Recommendation audit destination.
        now: Optional effective UTC timestamp.
        progress: Optional original progress observer.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar

    effects = LegacyRecommendationRun(
        sp,
        lastfm,
        playlist_id,
        export_path,
        recent_path,
        cache_path,
        log_path,
        progress,
    )
    workflow = RecommendationRun(
        effects,
        RecommendationStages(
            recommendation_seeds(),
            candidate_gathering(lastfm, cache_path, log_path, None, progress),
            recommendation_resolution(sp, progress),
        ),
        RecommendationClock(now),
        BerlinCalendar(),
        OptionalMessages(progress),
        legacy.DEFAULT_COUNT,
        legacy.MIN_WEEKLY_CANDIDATE_POOL,
        legacy.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
    )
    return workflow


@dataclass(frozen=True)
class RecommendationClock:
    """Retain the optional effective calendar value.

    Args:
        override: Original caller-selected date or instant.
    """

    override: datetime | None

    def now(self) -> datetime:
        """Observe the original effective date at its existing boundary.

        Returns:
            Original normalized date or instant.
        """
        return _generated_at(self.override)
