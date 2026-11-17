"""Time-capsule results with explicit source coverage and comparable periods."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from spotify_manager.domain.listening_values import RankedEntity


@dataclass(frozen=True)
class EraPeriod:
    """Describe the actual selected portion of a calendar period.

    Args:
        label: ISO month or year.
        start: Inclusive selected local start.
        end: Inclusive selected local end.
        plays: Recorded observations in the period.
        artists: Distinct recorded artists.
        covered: Whether the period intersects source coverage.
        partial: Whether selection or source boundaries cut the period.
    """

    label: str
    start: date
    end: date
    plays: int
    artists: int
    covered: bool
    partial: bool


@dataclass(frozen=True)
class ListeningEras:
    """Compare full artist-share vectors using weighted Jaccard similarity.

    Args:
        grain: Months, or years for selections exceeding 240 months.
        periods: Chronological calendar periods, including empty ones.
        similarities: Symmetric row/column matrix; empty comparisons are None.
    """

    grain: Literal["month", "year"]
    periods: tuple[EraPeriod, ...]
    similarities: tuple[tuple[float | None, ...], ...]


@dataclass(frozen=True)
class AnniversaryDay:
    """Describe this calendar anniversary in one earlier year.

    Args:
        day: Exact local anniversary date; leap days are never shifted.
        plays: Recorded observations on that day.
        artists: Distinct recorded artists.
        top_artists: At most five artists with shares of this day's plays.
        covered: Whether the day lies inside source coverage.
        partial: Whether the source starts or ends on this day.
    """

    day: date
    plays: int
    artists: int
    top_artists: tuple[RankedEntity, ...]
    covered: bool
    partial: bool


@dataclass(frozen=True)
class ListeningAnniversaries:
    """Explore earlier anniversaries independently of the visible start date.

    Args:
        as_of: Selected analysis end date defining the anniversary.
        days: Chronological earlier anniversaries, including covered zero days.
        observed_from: First recorded local source date, or None.
        observed_through: Last recorded local source date, or None.
    """

    as_of: date
    days: tuple[AnniversaryDay, ...]
    observed_from: date | None
    observed_through: date | None
