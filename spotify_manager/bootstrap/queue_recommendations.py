"""Compose Queue recommendation policy with original synchronous boundaries."""

from datetime import date
from datetime import datetime
from pathlib import Path

from spotify_manager.application.queue_recommendations import QueueRecommendations
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.infrastructure.legacy.queue_recommendations import (
    LegacyQueueNeighborhoods,
)
from spotify_manager.routines import the_queue as legacy


def gather_queue_recommendations(
    reader: legacy.LastFmReader,
    seeds: tuple[ArtistSeed, ...],
    heard: set[str],
    cache_path: Path,
    log_path: Path,
    week: date | None,
    limit: int,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> tuple[ArtistRecommendation, ...]:
    """Bind original cache, calendar, client and presenter seams.

    Args:
        reader: Caller-owned original Last.fm reader.
        seeds: Original ordered weighted seeds.
        heard: Original heard artist identities.
        cache_path: Original cache location.
        log_path: Original previous-addition log location.
        week: Optional original listening week.
        limit: Original candidate slice limit.
        now: Optional original timestamp.
        progress: Optional original progress presenter.

    Returns:
        Original ordered artist recommendations.
    """
    edge = LegacyQueueNeighborhoods(reader, cache_path, log_path, now, progress)
    return QueueRecommendations(
        edge,
        edge.neighbors,
        edge.clock,
        legacy.found_art.listening_week_start,
        edge.progress,
    ).run(seeds, heard, week, limit)
