"""Reconnectable manual Spotify matching requests and display values."""

from pydantic import BaseModel


class TrackMatchOption(BaseModel):
    """One unfiltered Spotify search result available for explicit selection."""

    spotify_id: str
    track: str
    artists: list[str]
    album: str
    url: str


class TrackMatchPendingChoice(BaseModel):
    """One historical play awaiting a selection, rejection or cancellation."""

    request_id: str
    scrobble: str
    candidates: list[TrackMatchOption]


class TrackMatchChoiceRequest(BaseModel):
    """Select a track ID or submit an empty choice for no match."""

    request_id: str
    choice: str
