"""Stable discovery HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class NewKidsReleaseOption(BaseModel):
    """One ranked release offered by an interactive New Kids job."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    popularity: int | None = None
    top_track_rank: int | None = None
    saved: bool = False


class NewKidsPendingChoice(BaseModel):
    """Current New Kids release choice exposed to the web client."""

    artist: str
    releases: list[NewKidsReleaseOption] = Field(default_factory=list)


class NewKidsTrackResult(BaseModel):
    """One completed New Kids artist decision."""

    artist: str
    source_track: str
    source_release: str
    current_liked: bool
    consecutive_unliked: int
    action: str
    target_track: str | None = None
    target_release: str | None = None
    release_number: int | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    qualification_reasons: list[str] = Field(default_factory=list)
    composer_playlist: str | None = None
    composer_position: int | None = None
    composer_limit: int | None = None


class NewKidsFillResult(BaseModel):
    """One Queue 2 marker handled while filling New Kids."""

    artist: str
    track: str
    action: str


class NewKidsChoiceRequest(BaseModel):
    """Release or control choice submitted to a waiting New Kids job."""

    choice: str


class Queue3ReleaseOption(BaseModel):
    """One current or next Queue 3 release shown at a boundary."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int


class Queue3ComposerPlaylistOption(BaseModel):
    """One owned composer playlist offered to a Queue 3 job."""

    spotify_id: str
    name: str
    total_tracks: int


class Queue3PendingChoice(BaseModel):
    """Current Queue 3 release or composer-playlist decision."""

    kind: Literal["release", "composer_playlist"]
    artist: str
    source_track: str | None = None
    current_release: Queue3ReleaseOption | None = None
    next_release: Queue3ReleaseOption | None = None
    playlists: list[Queue3ComposerPlaylistOption] = Field(default_factory=list)


class Queue3TrackResult(BaseModel):
    """One completed Queue 3 artist transition."""

    artist: str
    source_track: str
    source_release: str
    action: str
    target_track: str | None = None
    target_release: str | None = None
    album_decision: str | None = None
    album_liked_tracks: int | None = None
    album_total_tracks: int | None = None
    composer_playlist: str | None = None
    reason: str | None = None


class Queue3AnnualImportEntry(BaseModel):
    """One previous-year discovery considered during Queue 3 fill-up."""

    artist: str
    track: str
    source_year: int
    action: str


class Queue3ChoiceRequest(BaseModel):
    """Release, composer-playlist, or quit choice for Queue 3."""

    choice: str
