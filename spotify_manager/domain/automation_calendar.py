"""Original local maintenance windows, rebuild dates and artifact freshness."""

from datetime import UTC
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import tzinfo


def scrobble_rebuild_due(now: datetime, timezone: tzinfo) -> bool:
    """Select January 1 and the first Sunday of each Berlin calendar month.

    Args:
        now: Caller-owned original instant.
        timezone: Original local maintenance timezone.

    Returns:
        Original calendar decision or UTC boundary.
    """
    local = now.astimezone(timezone)
    return (local.month == 1 and local.day == 1) or (
        local.weekday() == 6 and local.day <= 7
    )


def maintenance_deadline(now: datetime, timezone: tzinfo) -> datetime:
    """Return 05:00 Berlin for a scheduled run, or five hours for a manual run.

    Args:
        now: Caller-owned original instant.
        timezone: Original local maintenance timezone.

    Returns:
        Original calendar decision or UTC boundary.
    """
    local_now = now.astimezone(timezone)
    if local_now.hour < 5:
        deadline_date = local_now.date()
    elif local_now.hour >= 22:
        deadline_date = (local_now + timedelta(days=1)).date()
    else:
        return now + timedelta(hours=5)
    local_deadline = datetime.combine(
        deadline_date,
        time(hour=5),
        tzinfo=timezone,
    )
    return local_deadline.astimezone(UTC)


def scheduled_window_is_open(now: datetime, timezone: tzinfo) -> bool:
    """Return whether a delayed scheduled run is still inside 22:00-05:00.

    Args:
        now: Caller-owned original instant.
        timezone: Original local maintenance timezone.

    Returns:
        Original calendar decision or UTC boundary.
    """
    local_hour = now.astimezone(timezone).hour
    return local_hour >= 22 or local_hour < 5


def maintenance_window_start(now: datetime, timezone: tzinfo) -> datetime:
    """Return the opening 22:00 boundary for the active Berlin window.

    Args:
        now: Caller-owned original instant.
        timezone: Original local maintenance timezone.

    Returns:
        Original calendar decision or UTC boundary.
    """
    local_now = now.astimezone(timezone)
    window_date = (
        local_now.date() - timedelta(days=1) if local_now.hour < 5 else local_now.date()
    )
    local_start = datetime.combine(
        window_date,
        time(hour=22),
        tzinfo=timezone,
    )
    return local_start.astimezone(UTC)


def artifacts_are_fresh(
    updated: dict[str, datetime], required: frozenset[str], threshold: datetime
) -> bool:
    """Require every original artifact at or after the maintenance opening.

    Args:
        updated: Last valid observation per artifact in original encounter order.
        required: Original complete artifact identities.
        threshold: Original maintenance opening instant.

    Returns:
        Original inclusive freshness decision.
    """
    if not required <= updated.keys():
        return False
    for name in required:
        if updated[name] < threshold:
            return False
    return True
