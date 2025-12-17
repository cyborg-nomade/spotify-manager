"""Simplified artist models."""

from pydantic import BaseModel


class SimplifiedArtist(BaseModel):
    """Simplified artist model."""

    spotify_id: str
    name: str
