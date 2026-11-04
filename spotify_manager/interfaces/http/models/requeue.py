"""Successor-album interactions for Requeue for a Dream jobs."""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class RequeuePendingChoice(BaseModel):
    """One eligible successor offered before applying a playlist transition."""

    request_id: str
    artist: str
    source_track: str
    source_release: str
    release_id: str
    release_name: str
    release_type: str
    release_date: str
    total_tracks: int


class RequeueChoiceRequest(BaseModel):
    """A decision bound to exactly one displayed successor album."""

    request_id: str = Field(min_length=1)
    choice: Literal["accept", "skip", "cancel"]
