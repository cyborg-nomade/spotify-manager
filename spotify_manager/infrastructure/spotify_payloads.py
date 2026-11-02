"""Describe unchecked SDK fields without changing their native failure behavior.

These annotations narrow opaque responses at concrete integration edges. They do
not validate, copy, coerce or discard values returned by caller-owned SDKs.
"""

from typing import TypedDict


class ArtistCredit(TypedDict, total=False):
    """Name the original optional identity fields in a Spotify artist credit.

    Args:
        id: Original artist identifier, when present.
        name: Original artist display name, when present.
    """

    id: str
    name: str


class AlbumCredits(TypedDict):
    """Name the metadata consumed by legacy first-credit lookups.

    Args:
        name: Original album display name.
        artists: Original ordered, potentially empty artist credits.
    """

    name: str
    artists: list[ArtistCredit]


class CreatedPlaylist(TypedDict):
    """Name the identity returned by the original playlist-creation endpoint.

    Args:
        id: Original created playlist identifier.
    """

    id: str
