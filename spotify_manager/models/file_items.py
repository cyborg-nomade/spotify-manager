"""File items models."""

from pydantic import BaseModel

from spotify_manager.models.albums import SimplifiedAlbum


class ControlFileItem(BaseModel):
    album: SimplifiedAlbum
    result: str
