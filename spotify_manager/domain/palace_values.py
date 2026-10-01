"""Historical Palace selections and live first-marker outcomes."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from spotify_manager.domain.history import HistoricalAlbum


SelectionSource = Literal["alphabetical", "history"]
SelectionAction = Literal["added", "already present", "duplicate selection", "no match"]


@dataclass(frozen=True)
class HistoricalAlbumSelection:
    """One Random.org date mapped to a ranked Last.fm album.

    Args:
        selected_date: Original Random.org-selected history date.
        date_index: Original zero-based index in the eligible date list.
        albums_on_date: Original count of ranked albums on the selected date.
        position: Original one-based selected rank.
        album: Original display title or ranked historical album facts.
    """

    selected_date: date
    date_index: int
    albums_on_date: int
    position: int
    album: HistoricalAlbum


@dataclass(frozen=True)
class SpotifyAlbum:
    """One Spotify album selected for first-track resolution.

    Args:
        spotify_id: Original Spotify identity.
        uri: Original Spotify reference.
        artist: Original artist display spelling.
        album: Original display title or ranked historical album facts.
        saved: Observed Saved Albums membership.
        similarity: Original qualified album-title similarity.
    """

    spotify_id: str
    uri: str
    artist: str
    album: str
    saved: bool
    similarity: float


@dataclass(frozen=True)
class SpotifyFirstTrack:
    """The first playable track in Spotify disc and track order.

    Args:
        spotify_id: Original Spotify identity.
        uri: Original Spotify reference.
        name: Original track display title.
    """

    spotify_id: str
    uri: str
    name: str


@dataclass(frozen=True)
class CatalogAlbum:
    """Complete original search observations before artist/title qualification.

    Args:
        spotify_id: Original parsed release identity.
        uri: Original parsed release reference.
        name: Original parsed release title.
        artists: Original ordered complete artist display names.
        rank: Original one-based raw search position.
    """

    spotify_id: str
    uri: str
    name: str
    artists: tuple[str, ...]
    rank: int


@dataclass(frozen=True)
class PalaceAlbumResult:
    """One alphabetical or historical album selection and its outcome.

    Args:
        source: Original alphabetical or historical selection recipe.
        artist: Original artist display spelling.
        album: Original display title or ranked historical album facts.
        spotify_album: Original resolved release, if any.
        first_track: Original first marker, if any.
        action: Original live-membership classification.
        selected_date: Original Random.org-selected history date.
        date_index: Original zero-based index in the eligible date list.
        albums_on_date: Original count of ranked albums on the selected date.
        history_position: Original one-based selected historical rank, if applicable.
        scrobbles: Original historical album play count, if applicable.
    """

    source: SelectionSource
    artist: str
    album: str
    spotify_album: SpotifyAlbum | None
    first_track: SpotifyFirstTrack | None
    action: SelectionAction
    selected_date: date | None = None
    date_index: int | None = None
    albums_on_date: int | None = None
    history_position: int | None = None
    scrobbles: int | None = None
