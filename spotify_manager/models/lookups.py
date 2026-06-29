"""Models for live library lookups (artist stats and album evaluation)."""

from pydantic import BaseModel


class ArtistLibraryStats(BaseModel):
    """How much of a given artist is in the user's library."""

    artist_name: str
    artist_id: str | None
    liked_tracks: int
    saved_releases: int
    source: str


class AlbumTrackLikedStatus(BaseModel):
    """Liked status of a single track on an album."""

    name: str
    uri: str
    liked: bool


class AlbumEvaluation(BaseModel):
    """Keep/remove decision for an album based on liked tracks."""

    album_name: str
    album_id: str | None
    artist_name: str | None
    total_tracks: int
    liked_tracks: int
    liked_ratio: float
    threshold: float
    decision: str  # "keep" | "remove"
    tracks: list[AlbumTrackLikedStatus]
    source: str
