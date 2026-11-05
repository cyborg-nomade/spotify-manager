"""Stable something old HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class SomethingOldArtistOption(BaseModel):
    """One exact-name Spotify artist offered to the web client."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None


class SomethingOldReleaseOption(BaseModel):
    """One filtered studio album or EP offered for Something Old."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SomethingOldPreviousMode(BaseModel):
    """Recorded completed use of one available Something Old selection mode."""

    mode: Literal["lastfm_top_tracks", "spotify_top_tracks", "album"]
    count: int
    label: str
    last_chosen_at: str | None = None
    release_name: str | None = None
    provenance: Literal["applied", "audit", "recovered"] | None = None


class SomethingOldPendingChoice(BaseModel):
    """Current Something Old interaction exposed to the web client."""

    kind: Literal["artist", "mode", "album"]
    artist: str
    scrobbles: int
    average_scrobble_date: str
    spotify_artist: str | None = None
    artist_candidates: list[SomethingOldArtistOption] = Field(default_factory=list)
    releases: list[SomethingOldReleaseOption] = Field(default_factory=list)
    previous_modes: list[SomethingOldPreviousMode] = Field(default_factory=list)
    previous_choice_summary: str | None = None


class SomethingOldRankingEntry(BaseModel):
    """One Golden Oldies artist shown in the web ranking preview."""

    artist: str
    scrobbles: int
    average_scrobble_date: str


class SomethingOldTrackResult(BaseModel):
    """One Spotify track selected for Something Old."""

    spotify_id: str
    track: str
    album: str
    artists: list[str]
    source: str
    lastfm_scrobbles: int | None = None


class SomethingOldChoiceRequest(BaseModel):
    """One artist, source mode, album, or quit choice."""

    choice: str
