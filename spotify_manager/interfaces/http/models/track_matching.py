"""Reconnectable manual Spotify matching requests and display values."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class TrackMatchOption(BaseModel):
    """One unfiltered Spotify search result available for explicit selection."""

    spotify_id: str
    track: str
    artists: list[str]
    album: str
    url: str


class AlbumMatchOption(BaseModel):
    """One unfiltered album search result available for explicit selection."""

    spotify_id: str
    album: str
    artists: list[str]
    release_type: str
    release_date: str
    url: str


class TrackMatchPendingChoice(BaseModel):
    """One historical play awaiting a selection, rejection or cancellation."""

    request_id: str
    scrobble: str
    candidates: list[TrackMatchOption]
    kind: Literal["track", "album"] = "track"
    albums: list[AlbumMatchOption] = Field(default_factory=list)


class TrackMatchChoiceRequest(BaseModel):
    """Select a track ID or submit an empty choice for no match."""

    request_id: str
    choice: str
