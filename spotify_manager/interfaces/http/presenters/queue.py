"""Stable queue result serialization."""

from spotify_manager.interfaces.http.models.queue import QueueFillResultEntry
from spotify_manager.interfaces.http.models.queue import QueueFlushResultEntry
from spotify_manager.routines import the_queue


def queue_fill_result_entry(result: the_queue.FillResult) -> QueueFillResultEntry:
    """Convert one Queue recommendation into its stable web representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return QueueFillResultEntry(
        lastfm_artist=result.recommendation.artist,
        score=result.recommendation.score,
        best_match=result.recommendation.best_match,
        supporting_seeds=list(result.recommendation.supporting_seeds),
        spotify_artist=(
            result.spotify_artist.name if result.spotify_artist is not None else None
        ),
        spotify_artist_id=(
            result.spotify_artist.spotify_id
            if result.spotify_artist is not None
            else None
        ),
        track=result.track.name if result.track is not None else None,
        action=result.action,
        followed=result.followed,
    )


def queue_flush_result_entry(result: the_queue.FlushResult) -> QueueFlushResultEntry:
    """Convert one Queue top-track transition for web polling.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return QueueFlushResultEntry(
        artist=result.artist,
        source_track=result.source_track,
        action=result.action,
        top_tracks=result.top_tracks,
        top_liked_tracks=result.top_liked_tracks,
        total_liked_tracks=result.total_liked_tracks,
        target_track=result.target_track,
        target_release=result.target_release,
        reason=result.reason,
    )
