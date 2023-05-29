"""File items models."""

from pydantic import BaseModel

# UFI

from spotify_manager.models.albums import SimplifiedAlbum


class ControlFileItem(BaseModel):
    """Control File Item model."""

    album: SimplifiedAlbum
    result: str
