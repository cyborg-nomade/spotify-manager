"""Shared discovery helpers for user-owned classical works playlists."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from spotipy import Spotify
from unidecode import unidecode


PLAYLIST_PAGE_LIMIT = 50
COMPOSER_PLAYLIST_PREFIX = "[CD]"
GENERIC_ARTIST_TERMS = frozenset(
    {
        "band",
        "choir",
        "chorus",
        "collective",
        "company",
        "ensemble",
        "experience",
        "group",
        "orchestra",
        "philharmonic",
        "players",
        "project",
        "quartet",
        "singers",
        "symphony",
        "trio",
    }
)
NAME_SUFFIXES = frozenset({"ii", "iii", "iv", "jr", "sr"})
RetryCall = Callable[[Callable[[], object], str], object]


class ComposerPlaylistError(RuntimeError):
    """Raised when owned Spotify playlists cannot be loaded safely."""


@dataclass(frozen=True)
class OwnedPlaylist:
    """One playlist owned by the authenticated Spotify account."""

    spotify_id: str
    name: str
    total_tracks: int


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


def load_owned_playlists(
    sp: Spotify,
    retry_call: RetryCall,
    anchor_playlist_ids: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Load owned playlists using any configured queue as the owner anchor."""
    raw_playlists: list[object] = []
    offset = 0
    while True:
        response = retry_call(
            partial(
                sp.current_user_playlists,
                limit=PLAYLIST_PAGE_LIMIT,
                offset=offset,
            ),
            f"loading owned playlists at offset {offset}",
        )
        if not isinstance(response, dict) or not isinstance(
            response.get("items"), list
        ):
            raise ComposerPlaylistError("Spotify returned invalid user playlist data.")
        raw_items = response["items"]
        raw_playlists.extend(raw_items)
        offset += len(raw_items)
        total = response.get("total")
        has_more = bool(response.get("next"))
        if isinstance(total, int):
            has_more = has_more or offset < total
        if not has_more:
            break
        if not raw_items:
            raise ComposerPlaylistError("Spotify returned an empty user-playlist page.")

    owner_id = ""
    for raw_playlist in raw_playlists:
        if not isinstance(raw_playlist, dict):
            continue
        if str(raw_playlist.get("id") or "") not in anchor_playlist_ids:
            continue
        owner = raw_playlist.get("owner")
        if isinstance(owner, dict):
            owner_id = str(owner.get("id") or "").strip()
        if owner_id:
            break
    if not owner_id:
        raise ComposerPlaylistError(
            "Could not establish playlist ownership from the configured queues."
        )
    return tuple(
        playlist
        for raw_playlist in raw_playlists
        if (playlist := _owned_playlist(raw_playlist, owner_id)) is not None
    )


def name_tokens(value: str) -> tuple[str, ...]:
    """Normalize a Spotify name for whole-token playlist matching."""
    return tuple(re.findall(r"[a-z0-9]+", unidecode(value).casefold()))


def _contains_tokens(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    """Return whether a complete token sequence occurs in another sequence."""
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def _surname_token(artist_tokens: tuple[str, ...]) -> str | None:
    """Return a safe personal-name surname for abbreviated playlist matching."""
    if len(artist_tokens) < 2:
        return None
    if (
        artist_tokens[0] == "the"
        or any(token in GENERIC_ARTIST_TERMS for token in artist_tokens)
        or any(
            any(character.isdigit() for character in token) for token in artist_tokens
        )
    ):
        return None
    surname_index = len(artist_tokens) - 1
    while surname_index > 0 and artist_tokens[surname_index] in NAME_SUFFIXES:
        surname_index -= 1
    surname = artist_tokens[surname_index]
    return surname if surname not in GENERIC_ARTIST_TERMS else None


def composer_playlist_candidates(
    artist_name: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    *,
    excluded_playlist_ids: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Match prefixed owned playlists containing a composer's name."""
    artist_tokens = name_tokens(artist_name)
    if not artist_tokens:
        return ()
    surname = _surname_token(artist_tokens)
    return tuple(
        playlist
        for playlist in owned_playlists
        if playlist.spotify_id not in excluded_playlist_ids
        and playlist.name.startswith(COMPOSER_PLAYLIST_PREFIX)
        and (
            _contains_tokens(name_tokens(playlist.name), artist_tokens)
            or (surname is not None and surname in name_tokens(playlist.name))
        )
    )


def is_composer_playlist_candidate(
    artist_name: str,
    playlist_id: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    *,
    excluded_playlist_ids: frozenset[str],
) -> bool:
    """Return whether one saved route still satisfies the current matcher."""
    return any(
        playlist.spotify_id == playlist_id
        for playlist in composer_playlist_candidates(
            artist_name,
            owned_playlists,
            excluded_playlist_ids=excluded_playlist_ids,
        )
    )
