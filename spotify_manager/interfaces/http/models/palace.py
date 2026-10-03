"""Stable palace HTTP request/response contracts."""

from pydantic import BaseModel


class PalaceAlbumSelectionResult(BaseModel):
    """One Palace of Memory album and its resolved first track."""

    source: str
    selected_date: str | None = None
    history_position: int | None = None
    albums_on_date: int | None = None
    artist: str
    album: str
    spotify_album: str | None = None
    first_track: str | None = None
    action: str


class PalaceAlbumRefreshResult(BaseModel):
    """Saved-album mirror refresh details shown by the web client."""

    previous: int
    current: int
    added: int
    removed: int
    skipped: int
    persisted: bool
    backup_path: str | None = None
