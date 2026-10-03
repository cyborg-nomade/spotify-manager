"""Stable releases HTTP request/response contracts."""

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class ReleaseCheckArtistOption(BaseModel):
    """One Spotify artist offered for a Last.fm artist mapping."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None
    exact_name: bool


class ReleaseCheckPendingChoice(BaseModel):
    """Current artist mapping or release approval exposed to the web client."""

    kind: Literal["artist", "release"]
    artist: str
    artist_rank: int
    artist_scrobbles: int
    artist_candidates: list[ReleaseCheckArtistOption] = Field(default_factory=list)
    release: str | None = None
    release_type: str | None = None
    release_date: str | None = None
    first_track: str | None = None
    destinations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    unattached_single: bool = False


class ReleaseCheckResultEntry(BaseModel):
    """One release decision and its destination-playlist outcomes."""

    artist: str
    artist_rank: int
    artist_scrobbles: int
    spotify_artist_id: str
    release_id: str
    release: str
    release_type: str
    release_date: str
    first_track_id: str | None = None
    first_track: str | None = None
    linked_future_release: str | None = None
    wine_cellar_action: str
    new_vintage_action: str
    reason: str | None = None
    dry_run: bool


class ReleaseCheckChoiceRequest(BaseModel):
    """One artist, custom search, release approval, skip, or quit choice."""

    choice: str


class ReleaseCheckStateSnapshot(BaseModel):
    """Versioned release-check state mirrored by the authenticated browser."""

    updated_at: str | None
    fingerprint: str
    state: dict[str, Any] | None = None
    backup_path: str | None = None


class ReleaseCheckStateRestoreRequest(BaseModel):
    """Optimistic restore request for a newer browser-held state copy."""

    expected_server_fingerprint: str
    state: dict[str, Any]
