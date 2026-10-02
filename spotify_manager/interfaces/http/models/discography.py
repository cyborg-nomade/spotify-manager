"""Stable discography HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from .something_old import SomethingOldArtistOption


class DiscographyReleaseOption(BaseModel):
    """One canonical release offered in a discography checklist."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    default: bool


class DiscographyPendingChoice(BaseModel):
    """Current release checklist or final confirmation shown by the web client."""

    kind: Literal["artist", "releases", "confirm"]
    artist: str | None = None
    queue: str | None = None
    artist_candidates: list[SomethingOldArtistOption] = Field(default_factory=list)
    releases: list[DiscographyReleaseOption] = Field(default_factory=list)
    default_release_ids: list[str] = Field(default_factory=list)


class DiscographyArtistResult(BaseModel):
    """One artist selected for the next discography batch."""

    spotify_id: str
    artist: str
    queue: str
    releases: int
    days: float
    release_names: list[str] = Field(default_factory=list)


class DiscographyChoiceRequest(BaseModel):
    """One release checklist, final approval, or cancellation response."""

    choice: str
    release_ids: list[str] = Field(default_factory=list)
