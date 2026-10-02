"""Original immutable Spotify mapping and track facts for Golden Oldies selection."""

from dataclasses import dataclass
from typing import Literal


type SelectionMode = Literal["lastfm_top_tracks", "spotify_top_tracks", "album"]


@dataclass(frozen=True)
class SpotifyArtistCandidate:
    """One original exact-name Spotify mapping for a Golden Oldies artist.

    Args:
        spotify_id: Original artist identity.
        name: Original display name.
        uri: Original artist URI.
        popularity: Original optional popularity.
        followers: Original optional follower count.
        search_rank: Original one-based search position.
    """

    spotify_id: str
    name: str
    uri: str
    popularity: int | None
    followers: int | None
    search_rank: int


@dataclass(frozen=True)
class SelectedTrack:
    """Original selected marker with its source and optional history evidence.

    Args:
        spotify_id: Original track identity.
        uri: Original playable track URI.
        track: Original display title.
        album: Original release display name.
        artists: Original ordered display credits.
        source: Original selection-source description.
        lastfm_scrobbles: Original optional exact-title play count.
    """

    spotify_id: str
    uri: str
    track: str
    album: str
    artists: tuple[str, ...]
    source: str
    lastfm_scrobbles: int | None = None
