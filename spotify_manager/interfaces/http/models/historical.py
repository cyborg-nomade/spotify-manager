"""Stable historical HTTP request/response contracts."""

from pydantic import BaseModel


class BlastSelectionResult(BaseModel):
    """One Last.fm selection and its Spotify playlist outcome."""

    selected_date: str
    page: int
    total_pages: int
    direction: str
    position: int
    lastfm_scrobble: str
    spotify_match: str | None = None
    liked: bool | None = None
    track_similarity: float | None = None
    album_similarity: float | None = None
    qualifying_matches: int = 0
    action: str


class DormantArtistResultEntry(BaseModel):
    """One dormant Last.fm artist and the liked track selected on Spotify."""

    artist: str
    scrobbles: int
    spotify_artist: str | None = None
    track: str | None = None
    popularity: int | None = None
    action: str
