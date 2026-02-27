"""Stats models."""

from pydantic import BaseModel


class StatsFileItem(BaseModel):
    """Stats file item model."""

    total_saved_albums: int
    total_listened_albums: int
    pct_listened_albums: float
    total_removed_albums: int
    pct_removed_albums: float
    total_kept_albums: int
    pct_kept_albums: float
    last_listened_to_index: int


class AlbumsStats(BaseModel):
    """Stats for albums."""

    total_saved_albums: int
    removed_albums: int
    added_albums: int
    growth: float


class ArtistsStats(BaseModel):
    """Stats for artists."""

    total_followed_artists: int
    removed_artists: int
    added_artists: int
    growth: float


class TracksStats(BaseModel):
    """Stats for tracks."""

    total_liked_tracks: int
    removed_tracks: int
    added_tracks: int
    growth: float


class StatsReport(BaseModel):
    """Monthly stats report."""

    albums_stats: AlbumsStats
    artists_stats: ArtistsStats
    tracks_stats: TracksStats
    avg_albums_per_artists: int
    avg_liked_tracks_per_artists: int
