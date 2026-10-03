"""Compose Queue recommendation policy with original synchronous boundaries."""

from datetime import datetime
from pathlib import Path

from spotify_manager.application.queue_recommendations import QueueRecommendations
from spotify_manager.infrastructure.legacy.queue_recommendations import (
    LegacyQueueNeighborhoods,
)
from spotify_manager.routines import the_queue as legacy


def queue_recommendations(
    reader: legacy.LastFmReader,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
    progress: legacy.ProgressCallback | None,
) -> QueueRecommendations:
    """Construct the invocation dependencies without executing the use case.

    Args:
        reader: Caller-owned original Last.fm reader.
        cache_path: Original cache location.
        log_path: Original previous-addition log location.
        now: Optional original timestamp.
        progress: Optional original progress presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.recommendation_calendar import (
        listening_week_start,
    )

    edge = LegacyQueueNeighborhoods(reader, cache_path, log_path, now, progress)
    return QueueRecommendations(
        edge,
        edge.neighbors,
        edge.clock,
        listening_week_start,
        edge.progress,
    )
