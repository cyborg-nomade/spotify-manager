"""Acquire discovery inputs before constructing the application stages."""

import json
from dataclasses import dataclass

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.state import AsyncRoutineState as RoutineState
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.interfaces.requests.discovery import DiscoveryInteraction
from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.discovery import DiscoveryResources
from spotify_manager.routines import new_kids as legacy
from spotify_manager.routines.composer_playlists import OwnedPlaylist


@dataclass(frozen=True)
class ReviewInputs:
    """Hold history and mutable state observed for one discovery review.

    Args:
        retry: Effective retry callback.
        active_year: Effective local calendar year.
        annual_scrobbles: Annual release progress.
        state_access: Caller-owned checkpoint authority.
        state: Original namespace or preview clone.
        owned_playlists: Owned works playlists excluding review destinations.
    """

    retry: RetryCall
    active_year: int
    annual_scrobbles: AnnualScrobbleIndex
    state_access: RoutineState
    state: dict[str, object]
    owned_playlists: tuple[OwnedPlaylist, ...]


async def review_inputs(
    sp: Spotify,
    options: DiscoveryOptions,
    interaction: DiscoveryInteraction,
    resources: DiscoveryResources,
) -> ReviewInputs:
    """Observe discovery history and state before starting a review.

    Args:
        sp: Caller-owned synchronous Spotify client.
        options: Configured destinations and execution mode.
        interaction: Operator decisions and notifications.
        resources: History, namespace, mirrors and audit files.

    Returns:
        The typed dependencies for this discovery stage.
    """
    from spotify_manager.infrastructure.discovery_history import (
        load_annual_scrobble_index,
    )
    from spotify_manager.infrastructure.discovery_history import (
        refresh_release_history as _refresh_history,
    )
    from spotify_manager.routines.composer_playlists import (
        async_load_owned_playlists as load_owned_playlists,
    )
    from spotify_manager.routines.new_kids import (
        _async_state_access as _async_state_access,
    )

    retry = interaction
    active_year = options.year or legacy.datetime.now().year
    await _refresh_history(
        resources.lastfm,
        resources.lastfm_username,
        "New Kids",
        resources.scrobbles_path,
        interaction,
        interaction,
    )
    interaction.progress(0, 0, f"Loading {active_year} Last.fm release history")
    annual_scrobbles = await load_annual_scrobble_index(
        resources.scrobbles_path, year=active_year
    )
    state_access = _async_state_access(resources.state_path, resources.state_service)
    persisted_state = await state_access.load()
    state = (
        json.loads(json.dumps(persisted_state)) if options.dry_run else persisted_state
    )
    try:
        owned_playlists = await load_owned_playlists(
            sp,
            retry,
            frozenset({options.new_kids_playlist_id, options.queue_2_playlist_id}),
        )
    except legacy.composer_playlists.ComposerPlaylistError as exc:
        raise legacy.NewKidsError(str(exc)) from exc
    return ReviewInputs(
        retry, active_year, annual_scrobbles, state_access, state, owned_playlists
    )
