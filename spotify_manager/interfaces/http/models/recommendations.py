"""Stable recommendations HTTP request/response contracts."""

from pydantic import BaseModel
from pydantic import Field


class FoundArtSelectionResult(BaseModel):
    """One Last.fm recommendation and its Spotify playlist outcome."""

    artist: str
    track: str
    score: float
    best_match: float
    supporting_seeds: list[str] = Field(default_factory=list)
    base_rank: int
    weekly_rank: float
    spotify_match: str | None = None
    track_similarity: float | None = None
    action: str


class SauvignonAlbumOption(BaseModel):
    """One materially distinct Spotify album edition offered to the user."""

    spotify_id: str
    artist: str
    album: str
    release_type: str
    release_date: str
    total_tracks: int


class SauvignonPendingChoice(BaseModel):
    """Current ambiguous Sauvignon album match shown by the web client."""

    artist: str
    album: str
    score: float
    best_match: float
    base_rank: int
    weekly_rank: float
    supporting_tracks: list[str] = Field(default_factory=list)
    options: list[SauvignonAlbumOption] = Field(default_factory=list)


class SauvignonSelectionResult(BaseModel):
    """One Last.fm-derived album recommendation and its Spotify outcome."""

    artist: str
    album: str
    score: float
    best_match: float
    supporting_tracks: list[str] = Field(default_factory=list)
    base_rank: int
    weekly_rank: float
    spotify_album: str | None = None
    spotify_album_id: str | None = None
    release_type: str | None = None
    release_date: str | None = None
    first_track: str | None = None
    action: str


class SauvignonChoiceRequest(BaseModel):
    """One album edition, skip, or quit choice for Sauvignon discovery."""

    choice: str
