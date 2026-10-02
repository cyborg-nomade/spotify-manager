"""Conservative name matching for owned classical works playlists."""

import re
from dataclasses import dataclass

from unidecode import unidecode


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
SURNAME_PLAYLIST_DESCRIPTORS = frozenset(
    {
        "all",
        "book",
        "by",
        "catalog",
        "catalogue",
        "cd",
        "chronological",
        "chronology",
        "complete",
        "composition",
        "compositions",
        "cycle",
        "discography",
        "music",
        "of",
        "opus",
        "part",
        "piece",
        "pieces",
        "playlist",
        "selection",
        "selections",
        "the",
        "track",
        "tracks",
        "vol",
        "volume",
        "work",
        "works",
    }
)


@dataclass(frozen=True)
class OwnedPlaylist:
    """One playlist owned by the authenticated Spotify account.

    Args:
        spotify_id: Original playlist identifier.
        name: Observed display name.
        total_tracks: Observed count, retaining the original parsing semantics.
    """

    spotify_id: str
    name: str
    total_tracks: int


def name_tokens(value: str) -> tuple[str, ...]:
    """Normalize a Spotify name for whole-token matching.

    Args:
        value: Original artist or playlist name.

    Returns:
        ASCII lowercase word and number tokens in their original order.
    """
    return tuple(re.findall(r"[a-z0-9]+", unidecode(value).casefold()))


def _contains_tokens(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    for index in range(len(haystack) - len(needle) + 1):
        if haystack[index : index + len(needle)] == needle:
            return True
    return False


def _has_digit(value: str) -> bool:
    return any(character.isdigit() for character in value)


def _personal_name(tokens: tuple[str, ...]) -> bool:
    if len(tokens) < 2 or tokens[0] == "the":
        return False
    for token in tokens:
        if token in GENERIC_ARTIST_TERMS or _has_digit(token):
            return False
    return True


def _surname_token(artist_tokens: tuple[str, ...]) -> str | None:
    if not _personal_name(artist_tokens):
        return None
    surname_index = len(artist_tokens) - 1
    while surname_index > 0 and artist_tokens[surname_index] in NAME_SUFFIXES:
        surname_index -= 1
    return artist_tokens[surname_index]


def _unambiguous_surname_match(playlist_name: str, surname: str | None) -> bool:
    if surname is None:
        return False
    playlist_tokens = name_tokens(playlist_name)
    if surname not in playlist_tokens:
        return False
    for token in playlist_tokens:
        if (
            token != surname
            and token not in SURNAME_PLAYLIST_DESCRIPTORS
            and not token.isdigit()
        ):
            return False
    return True


def _matches(
    playlist: OwnedPlaylist, tokens: tuple[str, ...], surname: str | None
) -> bool:
    if not playlist.name.startswith(COMPOSER_PLAYLIST_PREFIX):
        return False
    return _contains_tokens(
        name_tokens(playlist.name), tokens
    ) or _unambiguous_surname_match(playlist.name, surname)


def composer_playlist_candidates(
    artist_name: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    *,
    excluded_playlist_ids: frozenset[str],
) -> tuple[OwnedPlaylist, ...]:
    """Select prefixed owned playlists containing a composer's name.

    Args:
        artist_name: Full artist name used for exact or conservative surname matching.
        owned_playlists: Observed account-owned playlists in their existing order.
        excluded_playlist_ids: Queue and other playlists that cannot be routes.

    Returns:
        Matching playlists, preserving order and duplicate observations.
    """
    tokens = name_tokens(artist_name)
    if not tokens:
        return ()
    surname = _surname_token(tokens)
    candidates = []
    for playlist in owned_playlists:
        if playlist.spotify_id in excluded_playlist_ids:
            continue
        if _matches(playlist, tokens, surname):
            candidates.append(playlist)
    return tuple(candidates)


def is_composer_playlist_candidate(
    artist_name: str,
    playlist_id: str,
    owned_playlists: tuple[OwnedPlaylist, ...],
    *,
    excluded_playlist_ids: frozenset[str],
) -> bool:
    """Check whether a saved route still satisfies the current name policy.

    Args:
        artist_name: Current artist name.
        playlist_id: Previously selected route.
        owned_playlists: Current owned-playlist observations.
        excluded_playlist_ids: Playlists ineligible for routing.

    Returns:
        Whether the route remains among the matching candidates.
    """
    candidates = composer_playlist_candidates(
        artist_name,
        owned_playlists,
        excluded_playlist_ids=excluded_playlist_ids,
    )
    return any(playlist.spotify_id == playlist_id for playlist in candidates)
