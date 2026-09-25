"""Small values exchanged across the first listening integration ports."""

from dataclasses import dataclass
from typing import Protocol


class NamedTrack(Protocol):
    """Read-only track fields needed for playlist writes and their retry messages."""

    @property
    def uri(self) -> str:
        """Return the existing Spotify URI."""

    @property
    def name(self) -> str:
        """Return the existing display title."""


@dataclass(frozen=True)
class Album:
    """Resolved album identity, independent of SDK and wire models.

    Args:
        spotify_id: Resolved identifier.
        name: Display title.
        artist: Primary artist display name, when supplied by Spotify.
    """

    spotify_id: str
    name: str
    artist: str | None


@dataclass(frozen=True)
class Track:
    """Ordered catalog or playlist entry after boundary parsing.

    Args:
        spotify_id: Identifier, absent for unresolved catalog tracks.
        name: Existing display title.
        uri: Spotify URI used by playlist writes.
        membership_key: Original coerced identifier for legacy status lookups.
            Falsey raw identifiers are omitted from requests but still looked up
            by their string value; None uses the normal identifier conversion.
    """

    spotify_id: str | None
    name: str
    uri: str
    membership_key: str | None = None
