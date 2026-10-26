"""Compose The Queue's fill workflow with original caller-owned boundaries."""

from spotipy import Spotify

from spotify_manager.application.queue_artist_mapping import QueueArtistMapping
from spotify_manager.application.queue_fill import QueueFill
from spotify_manager.application.queue_fill import QueueFillStages
from spotify_manager.application.queue_seeds import QueueSeeds
from spotify_manager.bootstrap.queue_recommendations import queue_recommendations
from spotify_manager.infrastructure.legacy.queue_fill import LegacyQueueFill
from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.queue_fill import QueueFillResources
from spotify_manager.routines import the_queue as legacy


def queue_fill(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    options: QueueFillOptions,
    callbacks: QueueFillCallbacks,
    resources: QueueFillResources,
) -> QueueFill:
    """Build the queue fill application with invocation-owned inputs.

    Args:
        spotify: Caller-owned spotify.
        lastfm: Caller-owned lastfm.
        options: Caller-owned options.
        callbacks: Caller-owned callbacks.
        resources: Caller-owned resources.

    Returns:
        The configured application workflow.
    """
    edge = LegacyQueueFill(spotify, lastfm, options, callbacks, resources)
    return QueueFill(
        edge,
        QueueFillStages(
            QueueSeeds(BerlinCalendar(), legacy.SEED_POOL_MULTIPLIER),
            queue_recommendations(
                lastfm,
                resources.cache_path,
                resources.log_path,
                None,
                callbacks.progress_callback,
            ),
            QueueArtistMapping(edge, callbacks.choice_reader),
        ),
        legacy.DEFAULT_COUNT,
        legacy.CANDIDATE_POOL_MULTIPLIER,
        legacy.MIN_CANDIDATE_POOL,
        legacy.TOP_TRACK_LIMIT,
    )
