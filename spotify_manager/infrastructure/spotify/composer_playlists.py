"""Tolerant playlist paging and ownership observations for composer routes."""

from collections.abc import Callable
from typing import cast

from spotify_manager.domain.composers import OwnedPlaylist


class ComposerPlaylistError(RuntimeError):
    """Raised when owned Spotify playlists cannot be loaded safely."""


def _owned_playlist(raw: object, owner_id: str) -> OwnedPlaylist | None:
    """Parse one playlist only when it belongs to the expected owner."""
    if not isinstance(raw, dict):
        return None
    owner = raw.get("owner")
    if not isinstance(owner, dict) or str(owner.get("id") or "") != owner_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not spotify_id or not name:
        return None
    tracks = raw.get("tracks")
    total_tracks = (
        int(tracks.get("total", 0))
        if isinstance(tracks, dict) and isinstance(tracks.get("total", 0), int)
        else 0
    )
    return OwnedPlaylist(spotify_id, name, total_tracks)


def _page(response: object) -> dict[str, object]:
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        raise ComposerPlaylistError("Spotify returned invalid user playlist data.")
    return cast(dict[str, object], response)


def _has_more(response: dict[str, object], offset: int) -> bool:
    total = response.get("total")
    return bool(response.get("next")) or (isinstance(total, int) and offset < total)


def _collect(fetch_page: Callable[[int], object]) -> list[object]:
    playlists: list[object] = []
    offset = 0
    while True:
        response = _page(fetch_page(offset))
        items = cast(list[object], response["items"])
        playlists.extend(items)
        offset += len(items)
        if not _has_more(response, offset):
            return playlists
        if not items:
            raise ComposerPlaylistError("Spotify returned an empty user-playlist page.")


def _anchor_owner(raw: object, anchors: frozenset[str]) -> str:
    if not isinstance(raw, dict) or str(raw.get("id") or "") not in anchors:
        return ""
    owner = raw.get("owner")
    return str(owner.get("id") or "").strip() if isinstance(owner, dict) else ""


def _owner_id(playlists: list[object], anchors: frozenset[str]) -> str:
    for raw in playlists:
        owner_id = _anchor_owner(raw, anchors)
        if owner_id:
            return owner_id
    raise ComposerPlaylistError(
        "Could not establish playlist ownership from the configured queues."
    )


def observe_owned_playlists(
    fetch_page: Callable[[int], object],
    anchors: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Page account playlists and determine ownership from a configured queue.

    Args:
        fetch_page: Synchronous reader accepting the original item offset.
        anchors: Configured queue IDs used to establish the owner.

    Returns:
        Complete owned records in response order, including duplicates.

    Raises:
        ComposerPlaylistError: Pages are malformed or no owner can be established.
    """
    playlists = _collect(fetch_page)
    owner_id = _owner_id(playlists, anchors)
    owned = []
    for raw in playlists:
        playlist = _owned_playlist(raw, owner_id)
        if playlist is not None:
            owned.append(playlist)
    return tuple(owned)
