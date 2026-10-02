"""Resolve and retain owned composer-playlist routes at the original choice boundary."""

from collections.abc import Callable
from datetime import datetime
from typing import cast

from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.composers import composer_playlist_candidates
from spotify_manager.domain.discovery import RankedRelease


type ChoiceCandidate = RankedRelease | OwnedPlaylist
type ReleaseChoiceReader = Callable[[str, tuple[ChoiceCandidate, ...]], str]


def resolve_composer_route(
    state: dict[str, object],
    artist_id: str,
    artist_name: str,
    source_track_id: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    excluded_playlist_ids: frozenset[str],
    choose: ReleaseChoiceReader,
    clock: Callable[[], datetime],
) -> tuple[OwnedPlaylist | None, str | None]:
    """Reuse a valid route or remember the newly selected owned works playlist.

    Args:
        state: Mutable namespace; stale route removal remains an in-memory effect.
        artist_id: Logical composer identifier.
        artist_name: Name used by the existing owned-playlist matcher.
        source_track_id: Marker recorded only when accepting a new route.
        owned_playlists: Original owned-playlist observations.
        excluded_playlist_ids: Review queues that must not become composer routes.
        choose: Existing choice callback, including skip and quit responses.
        clock: Original UTC clock, read only when accepting a new route.

    Returns:
        Selected playlist and no control response, or an absent selection and control.

    Raises:
        NewKidsStateError: Composer route state is not a record.
        NewKidsError: The operator selects an unavailable playlist.
    """
    raw = state.get("composer_routes")
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids composer-route state is invalid.")
    routes = cast(dict[str, object], raw)
    candidates = composer_playlist_candidates(
        artist_name, owned_playlists, excluded_playlist_ids=excluded_playlist_ids
    )
    existing = _existing_route(routes, artist_id, candidates)
    if existing is not None:
        return existing, None
    if not candidates:
        return None, None
    selected = _select(artist_name, candidates, choose)
    if isinstance(selected, str):
        return None, selected
    routes[artist_id] = {
        "artist_name": artist_name,
        "playlist_id": selected.spotify_id,
        "playlist_name": selected.name,
        "current_track_id": source_track_id,
        "updated_at": clock().isoformat(),
    }
    return selected, None


def _existing_route(
    routes: dict[str, object], artist_id: str, candidates: tuple[OwnedPlaylist, ...]
) -> OwnedPlaylist | None:
    existing = routes.get(artist_id)
    if not isinstance(existing, dict):
        return None
    selected = _matching(candidates, str(existing.get("playlist_id") or ""))
    if selected is None:
        routes.pop(artist_id, None)
    return selected


def _select(
    artist_name: str, candidates: tuple[OwnedPlaylist, ...], choose: ReleaseChoiceReader
) -> OwnedPlaylist | str:
    if len(candidates) == 1:
        return candidates[0]
    choice = choose(artist_name, candidates)
    if choice in {"__skip__", "__quit__"}:
        return choice
    selected = _matching(candidates, choice)
    if selected is None:
        raise NewKidsError("Selected composer playlist is not available.")
    return selected


def _matching(
    candidates: tuple[OwnedPlaylist, ...], identifier: str
) -> OwnedPlaylist | None:
    for playlist in candidates:
        if playlist.spotify_id == identifier:
            return playlist
    return None
