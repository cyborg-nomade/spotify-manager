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
    monthly_history: dict
