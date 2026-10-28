"""Adapt only resource fields in retained Python invocation records."""

from dataclasses import replace

from spotify_manager.infrastructure.python_compat.golden import PythonGoldenAlbumChoice
from spotify_manager.infrastructure.python_compat.golden import PythonListeningMode
from spotify_manager.infrastructure.python_compat.golden import PythonOldArtistChoice
from spotify_manager.infrastructure.python_compat.history import PythonHistoryReader
from spotify_manager.infrastructure.python_compat.queue import PythonQueueArtistChoice
from spotify_manager.infrastructure.python_compat.queue_3 import PythonComposerChoice
from spotify_manager.infrastructure.python_compat.queue_3 import PythonQueueTransition
from spotify_manager.infrastructure.python_compat.recommendations import (
    PythonRecommendedAlbumChoice,
)
from spotify_manager.infrastructure.python_compat.release_check import (
    PythonReleaseArtistChoice,
)
from spotify_manager.infrastructure.python_compat.release_check import (
    PythonReleaseChoice,
)
from spotify_manager.infrastructure.python_compat.retry import PythonRetry
from spotify_manager.infrastructure.python_compat.runtime import PythonRandomIndexes
from spotify_manager.infrastructure.python_compat.wine import PythonWineEndpointChoice
from spotify_manager.infrastructure.python_compat.wine import PythonWineReleaseChoice
from spotify_manager.interfaces.requests.discovery import DiscoveryResources
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.palace import PalaceCallbacks
from spotify_manager.interfaces.requests.queue_3 import Queue3Callbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.sauvignon import SauvignonCallbacks
from spotify_manager.interfaces.requests.something_old import SomethingOldCallbacks


def python_queue3_callbacks(source: Queue3Callbacks) -> Queue3Callbacks:
    """Retain Queue3Callbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        transition_reader=PythonQueueTransition(source.transition_reader),
        composer_playlist_reader=PythonComposerChoice(source.composer_playlist_reader)
        if source.composer_playlist_reader is not None
        else None,
        retry_call=PythonRetry(source.retry_call)
        if source.retry_call is not None
        else None,
    )


def python_something_old_callbacks(
    source: SomethingOldCallbacks,
) -> SomethingOldCallbacks:
    """Retain SomethingOldCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        mode_reader=PythonListeningMode(source.mode_reader),
        album_choice_reader=PythonGoldenAlbumChoice(source.album_choice_reader),
        artist_choice_reader=PythonOldArtistChoice(source.artist_choice_reader)
        if source.artist_choice_reader is not None
        else None,
        retry_call=PythonRetry(source.retry_call),
    )


def python_new_wine_callbacks(source: NewWineCallbacks) -> NewWineCallbacks:
    """Retain NewWineCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        choose=PythonWineReleaseChoice(source.choose),
        endpoint=PythonWineEndpointChoice(source.endpoint)
        if source.endpoint is not None
        else None,
        retry=PythonRetry(source.retry) if source.retry is not None else None,
    )


def python_release_check_callbacks(
    source: ReleaseCheckCallbacks,
) -> ReleaseCheckCallbacks:
    """Retain ReleaseCheckCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        artist_choice_reader=PythonReleaseArtistChoice(source.artist_choice_reader)
        if source.artist_choice_reader is not None
        else None,
        release_choice_reader=PythonReleaseChoice(source.release_choice_reader)
        if source.release_choice_reader is not None
        else None,
        retry_call=PythonRetry(source.retry_call),
    )


def python_sauvignon_callbacks(source: SauvignonCallbacks) -> SauvignonCallbacks:
    """Retain SauvignonCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        choice_reader=PythonRecommendedAlbumChoice(source.choice_reader)
        if source.choice_reader is not None
        else None,
        retry_call=PythonRetry(source.retry_call)
        if source.retry_call is not None
        else None,
    )


def python_palace_callbacks(source: PalaceCallbacks) -> PalaceCallbacks:
    """Retain PalaceCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        random_index_reader=PythonRandomIndexes(source.random_index_reader),
        retry_call=PythonRetry(source.retry_call)
        if source.retry_call is not None
        else None,
    )


def python_discovery_resources(source: DiscoveryResources) -> DiscoveryResources:
    """Retain DiscoveryResources values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        lastfm=PythonHistoryReader(source.lastfm)
        if source.lastfm is not None
        else None,
    )


def python_queue_fill_callbacks(source: QueueFillCallbacks) -> QueueFillCallbacks:
    """Retain QueueFillCallbacks values and adapt its caller-owned I/O resources.

    Args:
        source: Original invocation values.

    Returns:
        The same invocation values with awaitable external resources.
    """
    return replace(
        source,
        choice_reader=PythonQueueArtistChoice(source.choice_reader)
        if source.choice_reader is not None
        else None,
        retry_call=PythonRetry(source.retry_call)
        if source.retry_call is not None
        else None,
    )
