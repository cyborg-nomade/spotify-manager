"""Stable wine HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class NewWineReleaseOption(BaseModel):
    """One release offered while a web flush waits for a choice."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_name: str


class NewWinePendingChoice(BaseModel):
    """Current interactive choice exposed to the web client."""

    kind: Literal["release", "album_endpoint"] = "release"
    artist: str
    source_track: str
    release: str | None = None
    track_position: int | None = None
    total_tracks: int | None = None
    terminal_release: bool = False
    releases: list[NewWineReleaseOption] = Field(default_factory=list)


class NewWineTrackResult(BaseModel):
    """One completed New Wine source-track decision."""

    artist: str
    source_track: str
    release: str
    release_type: str
    current_liked: bool
    consecutive_unliked: int
    action: str
    target_track: str | None = None
    album_unsaved: bool = False
    advance_reason: str | None = None
    drop_reason: str | None = None
    continuation_release: str | None = None
    continuation_track: str | None = None
    canonical_track_count: int | None = None
    canonical_cutoff_track: str | None = None


class NewWineCellarTrackResult(BaseModel):
    """One Wine Cellar entry moved or reconciled by a web flush."""

    artist: str
    source_track: str
    action: str
    liked_tracks: int | None = None
    saved_albums: int | None = None


class NewWineRefillResult(BaseModel):
    """Web representation of the post-flush Wine Cellar refill."""

    target_size: int
    before: int
    after: int
    added: int
    removed_from_cellar: int
    ineligible: int
    no_discovery: bool
    results: list[NewWineCellarTrackResult] = Field(default_factory=list)


class NewWineChoiceRequest(BaseModel):
    """Choice submitted for a waiting New Wine job."""

    choice: str
