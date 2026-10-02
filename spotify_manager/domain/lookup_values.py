"""Lookup identities, ambiguity errors and season values without runtime imports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ArtistNotFoundError(LookupError):
    """Signal an original missing artist lookup."""


class AmbiguousArtistError(LookupError):
    """Retain original exact-artist ambiguity and encounter-order candidates."""

    def __init__(self, message: str, candidates: list[dict[str, str]]) -> None:
        """Store original ambiguity facts.

        Args:
            message: Original visible error.
            candidates: Original ordered candidates.
        """
        super().__init__(message)
        self.candidates = candidates


class SpotifyLookupResponseError(RuntimeError):
    """Signal malformed original live lookup facts."""


class TracklistUnavailableError(LookupError):
    """Signal an uncached track list without an available client."""


class AlbumNotFoundError(LookupError):
    """Signal an original missing album lookup."""


class AmbiguousAlbumError(LookupError):
    """Retain original exact-album ambiguity and encounter-order candidates."""

    def __init__(self, message: str, candidates: list[dict[str, str]]) -> None:
        """Store original ambiguity facts.

        Args:
            message: Original visible error.
            candidates: Original ordered candidates.
        """
        super().__init__(message)
        self.candidates = candidates


class TrackNotFoundError(LookupError):
    """Signal an original missing track lookup."""


class AmbiguousTrackError(LookupError):
    """Retain original title ambiguity between primary artists."""

    def __init__(self, message: str, candidates: list[dict[str, str]]) -> None:
        """Store original ambiguity facts.

        Args:
            message: Original visible error.
            candidates: Original ordered candidates.
        """
        super().__init__(message)
        self.candidates = candidates


@dataclass(frozen=True)
class ResolvedTrack:
    """Original track identity required for matching listening history.

    Args:
        spotify_id: Original catalog identity.
        name: Original trimmed title.
        primary_artist: Original trimmed first artist credit.
        album: Original optional album display name.
        popularity: Original integer popularity, including booleans.
    """

    spotify_id: str
    name: str
    primary_artist: str
    album: str | None
    popularity: int


@dataclass(frozen=True)
class SeasonWindow:
    """One original local meteorological season.

    Args:
        label: Original season display label.
        start: Original inclusive local boundary.
        end: Original exclusive local boundary.
    """

    label: str
    start: datetime
    end: datetime


class SavedAlbum(Protocol):
    """Read original album identity and display facts without file model imports."""

    @property
    def spotify_id(self) -> str:
        """Read original album identity.

        Returns:
            Original Spotify identity.
        """
        ...

    @property
    def album(self) -> str:
        """Read original album display name.

        Returns:
            Original album name.
        """
        ...

    @property
    def artist(self) -> str:
        """Read original primary artist display name.

        Returns:
            Original artist name.
        """
        ...


@dataclass(frozen=True)
class LiveAlbumCandidate:
    """Original live album identity and distinct matching/display artist names.

    Args:
        spotify_id: Original trimmed identity.
        name: Original untrimmed name used in ambiguity presentation.
        primary_artist: Original trimmed first credit or none.
        display_artist: Original untrimmed first credit for ambiguity presentation.
    """

    spotify_id: str
    name: str
    primary_artist: str | None
    display_artist: str
