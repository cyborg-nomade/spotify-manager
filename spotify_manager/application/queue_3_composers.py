"""Resolve Queue 3 composer routes and advance through owned works playlists."""

from collections.abc import Callable
from dataclasses import asdict
from typing import cast

from spotify_manager.application.queue_3_values import Queue3ConfigError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.composers import composer_playlist_candidates
from spotify_manager.domain.discovery_progression import composer_source_index
from spotify_manager.domain.queue_3 import source_release


type ComposerReader = Callable[[str, tuple[OwnedPlaylist, ...]], str]


def resolve_composer_route(
    artist_id: str,
    artist_name: str,
    source_id: str,
    playlist_id: str,
    owned: tuple[OwnedPlaylist, ...],
    state: dict[str, object],
    choose: ComposerReader | None,
    now: Callable[[], str],
) -> tuple[OwnedPlaylist | None, bool]:
    """Reuse a valid route or accept a newly selected owned works playlist.

    Args:
        artist_id: Logical composer identifier.
        artist_name: Name used for conservative playlist matching.
        source_id: Original marker recorded only for a newly accepted route.
        playlist_id: Queue 3 destination excluded from works candidates.
        owned: Observed owned playlists.
        state: Mutable namespace retaining stale-route removal on cancellation.
        choose: Optional callback for ambiguous candidates.
        now: Original clock read only after accepting a new selection.

    Returns:
        Selected playlist and false, or no playlist and whether the user paused.

    Raises:
        Queue3ConfigError: Ambiguous candidates lack a reader or its choice is invalid.
        KeyError: The composer route container is missing.
    """
    routes = cast(dict[str, object], state["composer_routes"])
    candidates = composer_playlist_candidates(
        artist_name, owned, excluded_playlist_ids=frozenset({playlist_id})
    )
    existing = _existing(routes, artist_id, candidates)
    if existing is not None:
        return existing, False
    if not candidates:
        return None, False
    selected = _choose(artist_name, candidates, choose)
    if selected is None:
        return None, True
    routes[artist_id] = {
        "artist_name": artist_name,
        "playlist_id": selected.spotify_id,
        "playlist_name": selected.name,
        "current_track_id": source_id,
        "updated_at": now(),
    }
    return selected, False


def _existing(
    routes: dict[str, object], artist_id: str, candidates: tuple[OwnedPlaylist, ...]
) -> OwnedPlaylist | None:
    existing = routes.get(artist_id)
    if not isinstance(existing, dict):
        return None
    selected = _matching(candidates, str(existing.get("playlist_id") or ""))
    if selected is None:
        routes.pop(artist_id, None)
    return selected


def _choose(
    artist_name: str,
    candidates: tuple[OwnedPlaylist, ...],
    choose: ComposerReader | None,
) -> OwnedPlaylist | None:
    if len(candidates) == 1:
        return candidates[0]
    if choose is None:
        names = ", ".join(candidate.name for candidate in candidates)
        raise Queue3ConfigError(
            f"Multiple owned playlists match {artist_name}: {names}."
        )
    selected_id = choose(artist_name, candidates)
    if selected_id == "quit":
        return None
    selected = _matching(candidates, selected_id)
    if selected is None:
        raise Queue3ConfigError(
            f"The selected playlist is not an owned match for {artist_name}."
        )
    return selected


def _matching(
    candidates: tuple[OwnedPlaylist, ...], identifier: str
) -> OwnedPlaylist | None:
    for candidate in candidates:
        if candidate.spotify_id == identifier:
            return candidate
    return None


def composer_plan(
    source: PlaylistTrack, playlist: OwnedPlaylist, tracks: tuple[PlaylistTrack, ...]
) -> dict[str, object]:
    """Plan the next distinct marker using owned playlist order.

    Args:
        source: Original current marker.
        playlist: Accepted owned works playlist.
        tracks: Ordered works markers, including duplicate track IDs.

    Returns:
        Original composer advance, complete or skip record without live evaluation.
    """
    index = composer_source_index(source, tracks)
    if index is None:
        return _record(
            source,
            playlist,
            "skip",
            None,
            "current marker was not found in the composer playlist",
        )
    target = _next_marker(source, tracks[index + 1 :])
    if target is None:
        return _record(
            source, playlist, "complete", None, "last track of the composer playlist"
        )
    return _record(
        source,
        playlist,
        "composer_advance",
        target,
        "advanced through the owned composer playlist in playlist order",
    )


def _next_marker(
    source: PlaylistTrack, tracks: tuple[PlaylistTrack, ...]
) -> PlaylistTrack | None:
    for track in tracks:
        if track.spotify_id != source.spotify_id:
            return track
    return None


def _record(
    source: PlaylistTrack,
    playlist: OwnedPlaylist,
    action: str,
    target: PlaylistTrack | None,
    reason: str,
) -> dict[str, object]:
    target_release = source_release(target) if target is not None else None
    target_track = None
    if target is not None:
        target_track = ReleaseTrack(target.spotify_id, target.uri, target.name, 1, 1)
    return {
        "action": action,
        "current_release": asdict(source_release(source)),
        "target_release": asdict(target_release)
        if target_release is not None
        else None,
        "target": asdict(target_track) if target_track is not None else None,
        "evaluation": None,
        "composer_playlist_id": playlist.spotify_id,
        "composer_playlist_name": playlist.name,
        "reason": reason,
    }
