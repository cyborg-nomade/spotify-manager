"""Convert observed timestamps to the recommendation policy's local dates."""

from datetime import UTC
from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo

from spotify_manager.domain.recommendation_history import listening_week_start as week


BERLIN = ZoneInfo("Europe/Berlin")


def listening_week_start(value: datetime | date | None = None) -> date:
    """Find the Friday containing an observed Berlin date or timestamp.

    Args:
        value: Date or timestamp; naive timestamps mean UTC and None means now.

    Returns:
        The preceding or same-day Friday in the Berlin calendar.
    """
    if value is None:
        return week(datetime.now(BERLIN).date())
    if not isinstance(value, datetime):
        return week(value)
    stamp = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return week(stamp.astimezone(BERLIN).date())
