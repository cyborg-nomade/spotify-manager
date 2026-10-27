"""Retain the installed SDK's pure ID/URI normalization without constructing it."""

import re
from collections.abc import Sequence

from spotipy import Spotify
from spotipy.exceptions import SpotifyException


def spotify_id(kind: str, reference: str) -> str:
    """Normalize exactly the URI/URL/base-62 forms accepted by the frozen SDK.

    Args:
        kind: Expected Spotify resource kind.
        reference: Original identifier, URI or URL.

    Returns:
        Original normalized identifier.

    Raises:
        SpotifyException: Original kind mismatch or unsupported reference error.
    """
    uri = re.search(Spotify._regex_spotify_uri, reference)
    if uri is not None:
        return _matched_id(kind, uri, "URI")
    url = re.search(Spotify._regex_spotify_url, reference)
    if url is not None:
        return _matched_id(kind, url, "URL")
    if re.search(Spotify._regex_base62, reference) is not None:
        return reference
    raise SpotifyException(400, -1, "Unsupported URL / URI.")


def _matched_id(kind: str, match: re.Match[str], label: str) -> str:
    if match.group("type") != kind:
        raise SpotifyException(400, -1, f"Unexpected Spotify {label} type.")
    return match.group("id")


def spotify_uri(kind: str, reference: str) -> str:
    """Retain valid URIs verbatim and normalize other forms through the SDK rule.

    Args:
        kind: Requested resource kind.
        reference: Original identifier, URI or URL.

    Returns:
        Original compatible Spotify URI.
    """
    if re.search(Spotify._regex_spotify_uri, reference) is not None:
        return reference
    return "spotify:" + kind + ":" + spotify_id(kind, reference)


def joined_ids(kind: str, references: Sequence[str]) -> str:
    """Join normalized identities without deduplicating or reordering them.

    Args:
        kind: Expected resource kind.
        references: Original ordered references.

    Returns:
        Original comma-separated IDs.
    """
    ids = []
    for reference in references:
        ids.append(spotify_id(kind, reference))
    return ",".join(ids)


def joined_uris(kind: str, references: Sequence[str]) -> str:
    """Join original URI normalization results in caller order.

    Args:
        kind: Requested resource kind.
        references: Original ordered references.

    Returns:
        Original comma-separated URIs.
    """
    uris = []
    for reference in references:
        uris.append(spotify_uri(kind, reference))
    return ",".join(uris)
