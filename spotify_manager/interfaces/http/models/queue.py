"""Stable queue HTTP request/response contracts."""

from pydantic import BaseModel
from pydantic import Field


class QueueArtistOption(BaseModel):
    """One Spotify artist offered for a Last.fm Queue recommendation."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None
    exact_name: bool


class QueuePendingChoice(BaseModel):
    """Current Last.fm-to-Spotify artist mapping shown by the web client."""

    artist: str
    base_rank: int
    score: float
    supporting_seeds: list[str] = Field(default_factory=list)
    candidates: list[QueueArtistOption] = Field(default_factory=list)


class QueueFillResultEntry(BaseModel):
    """One Last.fm Queue recommendation resolved against Spotify."""

    lastfm_artist: str
    score: float
    best_match: float
    supporting_seeds: list[str] = Field(default_factory=list)
    spotify_artist: str | None = None
    spotify_artist_id: str | None = None
    track: str | None = None
    action: str
    followed: bool = False


class QueueFlushResultEntry(BaseModel):
    """One live top-track decision from a Queue flush."""

    artist: str
    source_track: str
    action: str
    top_tracks: int
    top_liked_tracks: int
    total_liked_tracks: int
    target_track: str | None = None
    target_release: str | None = None
    reason: str | None = None


class QueueChoiceRequest(BaseModel):
    """Artist mapping, custom search, skip, or quit choice for Queue fill."""

    choice: str
