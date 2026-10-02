"""Original meteorological season boundaries with an explicitly supplied zone."""

from datetime import datetime
from datetime import tzinfo

from spotify_manager.domain.lookup_values import SeasonWindow


def season_window(when: datetime, timezone: tzinfo) -> SeasonWindow:
    """Observe the original local meteorological season.

    Args:
        when: Original effective observation time.
        timezone: Original caller-owned local timezone.

    Returns:
        Original inclusive/exclusive season boundaries and label.
    """
    local = when.astimezone(timezone)
    year = local.year
    if 3 <= local.month <= 5:
        return SeasonWindow(
            f"Spring {year}",
            datetime(year, 3, 1, tzinfo=timezone),
            datetime(year, 6, 1, tzinfo=timezone),
        )
    if 6 <= local.month <= 8:
        return SeasonWindow(
            f"Summer {year}",
            datetime(year, 6, 1, tzinfo=timezone),
            datetime(year, 9, 1, tzinfo=timezone),
        )
    if 9 <= local.month <= 11:
        return SeasonWindow(
            f"Autumn {year}",
            datetime(year, 9, 1, tzinfo=timezone),
            datetime(year, 12, 1, tzinfo=timezone),
        )
    winter_year = year if local.month == 12 else year - 1
    return SeasonWindow(
        f"Winter {winter_year}/{winter_year + 1}",
        datetime(winter_year, 12, 1, tzinfo=timezone),
        datetime(winter_year + 1, 3, 1, tzinfo=timezone),
    )
