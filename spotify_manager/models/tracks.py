"""Simplified tracks models."""

from pydantic import BaseModel


class SimplifiedTrack(BaseModel):
    """Simplified track model."""

    disc_number: int
    track_number: int
    uri: str
