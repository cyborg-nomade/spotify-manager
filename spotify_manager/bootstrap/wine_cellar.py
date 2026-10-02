"""Compose synchronous refill and library-affinity boundaries."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.library_affinity import library_affinity
from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.wine_cellar import CellarOptions
from spotify_manager.application.wine_cellar import refill_cellar
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.infrastructure.legacy.wine_cellar import ArtistLibraryMembership
from spotify_manager.infrastructure.legacy.wine_cellar import WineCellarAccess
from spotify_manager.interfaces.presenters.wine_cellar import present_transfer


def run_cellar_refill(
    client: Spotify,
    retry: RetryCall,
    access: RoutineState,
    options: CellarOptions,
    state: dict[str, object],
    run: dict[str, object],
    log_path: Path,
    liked_path: Path,
    albums_path: Path,
    echo: Callable[[str], None],
) -> CellarRefillSummary:
    """Bind the existing refill integrations without owning their lifetimes.

    Args:
        client: Caller-owned synchronous client.
        retry: Existing retry/cancellation callback.
        access: Resolved namespace adapter.
        options: Original destination, eligibility and preview settings.
        state: Complete mutable namespace.
        run: Active run within the namespace.
        log_path: Original audit destination.
        liked_path: Canonical liked-track mirror.
        albums_path: Canonical saved-album mirror.
        echo: Existing message sink.

    Returns:
        Original refill summary.
    """
    integration = WineCellarAccess(
        client, retry, access, log_path, liked_path, albums_path
    )
    return refill_cellar(
        integration, options, state, run, partial(present_transfer, echo)
    )


def observe_library_affinity(
    client: Spotify,
    retry: RetryCall,
    artist: str,
    tracks: tuple[str, ...],
    albums: tuple[str, ...],
    batch_size: int,
    minimum_albums: int,
    minimum_tracks: int,
) -> tuple[int | None, int, bool]:
    """Bind live membership reads to the existing affinity thresholds.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing retry policy.
        artist: Display name retained in retry descriptions.
        tracks: Candidate track IDs in mirror order.
        albums: Candidate album IDs in mirror order.
        batch_size: Existing conservative batch size.
        minimum_albums: Saved-album threshold.
        minimum_tracks: Liked-track threshold.

    Returns:
        Liked count, saved-album count and qualification.
    """
    return library_affinity(
        ArtistLibraryMembership(client, artist, retry),
        albums,
        tracks,
        batch_size=batch_size,
        minimum_albums=minimum_albums,
        minimum_tracks=minimum_tracks,
    )
