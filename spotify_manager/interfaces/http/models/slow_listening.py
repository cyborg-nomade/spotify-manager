"""Stable slow listening HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class SlowListeningReleaseOption(BaseModel):
    """One equal-date release offered for chronological ordering."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SlowListeningPendingChoice(BaseModel):
    """Current Slow Listening interaction exposed to the web client."""

    kind: Literal["track", "release_order", "completion"]
    artist: str
    source_track: str | None = None
    source_release: str | None = None
    target_track: str | None = None
    target_release: str | None = None
    release_date: str | None = None
    releases: list[SlowListeningReleaseOption] = Field(default_factory=list)


class SlowListeningTrackResult(BaseModel):
    """One completed Slow Listening source-track transition."""

    artist: str
    source_track: str
    source_release: str
    action: str
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: list[str] = Field(default_factory=list)
    reason: str | None = None


class SlowListeningChoiceRequest(BaseModel):
    """Choice or release ordering submitted to a waiting web job."""

    choice: str
    order: list[str] = Field(default_factory=list)
