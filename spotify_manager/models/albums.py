"""Simplified album models."""

from pydantic import BaseModel

from spotify_manager.models.artists import SimplifiedArtist


class SimplifiedAlbum(BaseModel):
    """Simplified album model."""

    spotify_id: str
    name: str
    artist: SimplifiedArtist
    ordering_string: str
