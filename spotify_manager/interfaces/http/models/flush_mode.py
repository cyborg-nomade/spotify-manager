"""Typed HTTP controls and observations for global Flush Mode."""

from pydantic import BaseModel

from spotify_manager.domain.flush_mode import FlushControl


class FlushControlRequest(BaseModel):
    """Select a persistent operator override or return to Automatic."""

    control: FlushControl


class FlushModeStatus(BaseModel):
    """Present effective policy independently of automatic observations."""

    control: FlushControl
    active: bool
    automatic_active: bool
    queue_tracks: int | None
    queue_2_tracks: int | None
    checked_at: str | None
    attempted_at: str | None
    error: str | None
    reason: str
