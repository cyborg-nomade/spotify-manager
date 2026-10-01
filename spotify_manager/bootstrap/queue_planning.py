"""Compose original Queue planning reads with inner decisions and marker selection."""

from dataclasses import asdict

from spotipy import Spotify

from spotify_manager.application.queue_flush_planning import QueuePlanning
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.infrastructure.legacy.queue_planning import LegacyQueuePlanning
from spotify_manager.routines import the_queue as legacy


def plan_queue_entry(
    spotify: Spotify,
    source: PlaylistTrack,
    uris: list[str],
    retry: legacy.RetryCall,
) -> dict[str, object]:
    """Bind original catalog seams and present identical durable plan fields.

    Args:
        spotify: Original caller-owned Spotify client.
        source: Original authoritative source marker.
        uris: Original ordered live or fallback source URIs.
        retry: Original retry boundary.

    Returns:
        Original compatible plan record before accepted checkpointing.
    """
    access = LegacyQueuePlanning(spotify, retry)
    return asdict(QueuePlanning(access, legacy.TOP_TRACK_LIMIT).run(source, uris))
