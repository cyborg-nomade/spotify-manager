"""Typed queries and analytical results for recorded listening history."""

from dataclasses import dataclass
from datetime import date
from typing import Literal


type EntityKind = Literal["artist", "album", "track"]


@dataclass(frozen=True)
class ListeningQuery:
    """Select local calendar dates and optional artist/rhythm filters.

    Args:
        start: Inclusive first local date.
        end: Inclusive last local date.
        timezone: Valid IANA display timezone.
        artist: Optional analytics artist key.
        weekday: Optional Monday-based weekday.
        hour: Optional local hour.
    """

    start: date
    end: date
    timezone: str = "Europe/Berlin"
    artist: str | None = None
    weekday: int | None = None
    hour: int | None = None


@dataclass(frozen=True)
class RankingOptions:
    """Bound a searchable entity ranking or record page.

    Args:
        kind: Entity dimension.
        search: Substring of the display name or artist.
        page: One-based page.
        limit: Maximum returned entries.
        order: Descending play count or ascending name.
    """

    kind: EntityKind = "artist"
    search: str = ""
    page: int = 1
    limit: int = 25
    order: Literal["plays", "name"] = "plays"


@dataclass(frozen=True)
class EntitySelection:
    """Identify an entity within the analytics identity version.

    Args:
        kind: Artist, album, or track.
        key: Opaque deterministic analytics identifier.
    """

    kind: EntityKind
    key: str


@dataclass(frozen=True)
class RecordOptions:
    """Page recorded observations with an optional independent entity selection.

    Args:
        page: One-based record page.
        limit: Maximum returned observations.
        selection: Optional detail entity, separate from the global artist filter.
    """

    page: int = 1
    limit: int = 50
    selection: EntitySelection | None = None


@dataclass(frozen=True)
class RediscoveryOptions:
    """Select a favorite dimension and transparent minimum thresholds.

    Args:
        kind: Artist, album, or track dimension.
        minimum_plays: Inclusive historical-play threshold.
        minimum_gap: Inclusive calendar-day gap threshold.
    """

    kind: EntityKind = "artist"
    minimum_plays: int = 50
    minimum_gap: int = 365


@dataclass(frozen=True)
class ListeningCounts:
    """Keep exact filtered counts and observed UTC bounds together.

    Args:
        scrobbles: Recorded rows, including duplicates.
        artists: Distinct artist identities.
        tracks: Distinct artist/title identities.
        albums: Distinct known artist/album identities.
        active_days: Local dates with a recorded play.
        missing_album: Plays without an album name.
        first_ms: Earliest selected UTC observation, or none.
        last_ms: Latest selected UTC observation, or none.
    """

    scrobbles: int
    artists: int
    tracks: int
    albums: int
    active_days: int
    missing_album: int
    first_ms: int | None
    last_ms: int | None


@dataclass(frozen=True)
class ListeningOverview:
    """Present counts with explicit calendar-day and active-day averages.

    Args:
        counts: Exact filtered counts.
        calendar_days: Inclusive selected days, including empty dates.
        per_calendar_day: Recorded plays divided by selected calendar days.
        per_active_day: Recorded plays divided by populated calendar days.
    """

    counts: ListeningCounts
    calendar_days: int
    per_calendar_day: float
    per_active_day: float


@dataclass(frozen=True)
class ListeningDay:
    """Describe one local date and whether it intersects observed coverage.

    Args:
        day: Date in the selected display timezone.
        plays: Recorded rows on this date.
        covered: Whether the date falls within observed source bounds.
        partial: Whether the source starts or ends on this date.
    """

    day: date
    plays: int
    covered: bool
    partial: bool


@dataclass(frozen=True)
class ListeningHour:
    """Describe a weekday/hour cell with its actual covered-hour denominator.

    Args:
        weekday: Monday-based weekday index.
        hour: Local hour from zero through 23.
        plays: Recorded observations in this cell.
        occurrences: Covered hours, including fractional source boundaries.
        average: Recorded plays per covered hour, or zero without coverage.
    """

    weekday: int
    hour: int
    plays: int
    occurrences: float
    average: float


@dataclass(frozen=True)
class ListeningActivity:
    """Return complete daily buckets and all 168 weekly rhythm cells.

    Args:
        days: Ordered local calendar dates, including empty buckets.
        hours: Monday-first, hour-major weekly rhythm cells.
    """

    days: tuple[ListeningDay, ...]
    hours: tuple[ListeningHour, ...]


@dataclass(frozen=True)
class RankedEntity:
    """Describe a ranked entity with its share of all filtered scrobbles.

    Args:
        key: Opaque analytics identity.
        name: First encountered display spelling.
        artist: Display artist context, including for tracks/albums.
        plays: Filtered recorded-row count.
        share: Fraction of all filtered rows, before ranking-name search.
    """

    key: str
    name: str
    artist: str
    plays: int
    share: float


@dataclass(frozen=True)
class ListeningRanking:
    """Return a bounded ranking and total matching entities.

    Args:
        items: At most one page of ranked entities.
        total: All matching entities before pagination.
        page: One-based page number.
        limit: Requested maximum rows per page.
    """

    items: tuple[RankedEntity, ...]
    total: int
    page: int
    limit: int


@dataclass(frozen=True, slots=True)
class ArtistPlay:
    """Carry only the fields needed for artist evolution and discovery.

    Args:
        timestamp_ms: Recorded UTC milliseconds.
        artist_key: Stable analytics artist identity.
        artist_name: Original display artist.
        track_key: Artist-qualified track identity for breadth counts.
    """

    timestamp_ms: int
    artist_key: str
    artist_name: str
    track_key: str


@dataclass(frozen=True)
class ListeningSeries:
    """Keep one fixed artist series across all requested temporal buckets.

    Args:
        key: Stable artist identity, or other for the remainder.
        name: Display artist or Other label.
        counts: Recorded plays aligned to the result's temporal buckets.
    """

    key: str
    name: str
    counts: tuple[int, ...]


@dataclass(frozen=True)
class ListeningBreadth:
    """Describe recorded variety and top-artist concentration in a bucket.

    Args:
        artists: Distinct recorded artists in the bucket.
        tracks: Distinct artist-qualified tracks in the bucket.
        top_artist_share: Largest artist count divided by all bucket plays.
    """

    artists: int
    tracks: int
    top_artist_share: float


@dataclass(frozen=True)
class ListeningEvolution:
    """Return fixed top-eight-plus-Other series and aligned breadth metrics.

    Args:
        buckets: Ordered ISO months or Monday dates, including empty periods.
        series: Up to eight fixed artists plus the Other remainder.
        breadth: Variety and concentration aligned with the same buckets.
        grain: Calendar months or Monday-based weeks.
    """

    buckets: tuple[str, ...]
    series: tuple[ListeningSeries, ...]
    breadth: tuple[ListeningBreadth, ...]
    grain: Literal["week", "month"]


@dataclass(frozen=True)
class ListeningRecord:
    """Describe one recorded scrobble without asserting playback duration.

    Args:
        ordinal: Original source row position, preserving stable timestamp ties.
        timestamp_ms: Recorded UTC milliseconds.
        artist_key: Stable analytics artist identity.
        artist: Original source artist spelling.
        album: Original source album, possibly empty.
        track: Original source track spelling.
    """

    ordinal: int
    timestamp_ms: int
    artist_key: str
    artist: str
    album: str
    track: str


@dataclass(frozen=True)
class ListeningRecords:
    """Return one bounded record page with its full filtered row count.

    Args:
        items: Newest-first observations with stable source-order ties.
        total: All matching rows before pagination.
        page: One-based page number.
        limit: Requested maximum rows per page.
    """

    items: tuple[ListeningRecord, ...]
    total: int
    page: int
    limit: int


@dataclass(frozen=True)
class EntityLifetime:
    """Keep entity history through an explicit analysis cutoff.

    Args:
        key: Opaque analytics identity.
        name: First encountered display name.
        artist: Artist context for albums/tracks.
        plays: Recorded rows before the analysis cutoff.
        first_ms: First recorded UTC observation.
        last_ms: Last recorded UTC observation before the cutoff.
    """

    key: str
    name: str
    artist: str
    plays: int
    first_ms: int
    last_ms: int


@dataclass(frozen=True)
class ListeningEntity:
    """Separate lifetime facts from filtered details and related rankings.

    Args:
        kind: Opened artist, album, or track dimension.
        lifetime: Full pre-cutoff recorded history facts.
        overview: Counts within the visible shared selection.
        activity: Calendar/rhythm within the shared selection.
        records: First page of selected observations.
        related: Related track ranking within the same selection.
    """

    kind: EntityKind
    lifetime: EntityLifetime
    overview: ListeningOverview
    activity: ListeningActivity
    records: ListeningRecords
    related: ListeningRanking


@dataclass(frozen=True)
class DiscoveryCohort:
    """Report cohort returns only when the entire follow-up window is observed.

    Args:
        month: First-observed ISO month.
        artists: All first-observed artists in this cohort.
        eligible_7: Artists with seven fully observed follow-up days.
        returned_7: Eligible artists returning on another day within seven days.
        eligible_30: Artists with 30 fully observed follow-up days.
        returned_30: Eligible artists returning on another day within 30 days.
        eligible_90: Artists with 90 fully observed follow-up days.
        returned_90: Eligible artists returning on another day within 90 days.
    """

    month: str
    artists: int
    eligible_7: int
    returned_7: int
    eligible_30: int
    returned_30: int
    eligible_90: int
    returned_90: int


@dataclass(frozen=True)
class ListeningDiscoveries:
    """Return first-observed artist cohorts and the source follow-up boundary.

    Args:
        cohorts: Monthly cohorts with window-specific denominators.
        observed_through: Last complete follow-up calendar day, or none.
    """

    cohorts: tuple[DiscoveryCohort, ...]
    observed_through: date | None


@dataclass(frozen=True)
class ForgottenFavorite:
    """Describe lifetime counts and inactivity as of a selected local date.

    Args:
        entity: Full available history through the analysis cutoff.
        days_since_last: Local calendar-day gap to the analysis date.
    """

    entity: EntityLifetime
    days_since_last: int


@dataclass(frozen=True)
class ListeningRediscovery:
    """Return bounded forgotten favorites with transparent thresholds.

    Args:
        items: At most 100 favorites ordered by historical plays and gap.
        total: All qualifying entities before the display cap.
        as_of: Selected local analysis end date.
        minimum_plays: Inclusive historical-play threshold.
        minimum_gap: Inclusive calendar-day inactivity threshold.
    """

    items: tuple[ForgottenFavorite, ...]
    total: int
    as_of: date
    minimum_plays: int
    minimum_gap: int


@dataclass(frozen=True)
class ListeningChange:
    """Compare counts and percentage shares across two equally long periods.

    Args:
        key: Stable artist identity.
        name: Display artist name.
        previous: Recorded plays in the preceding equal-length period.
        current: Recorded plays in the visible selected period.
        previous_share: Fraction of all previous-period plays.
        current_share: Fraction of all selected-period plays.
    """

    key: str
    name: str
    previous: int
    current: int
    previous_share: float
    current_share: float


@dataclass(frozen=True)
class ListeningComparison:
    """Report a previous-period comparison with explicit coverage bounds.

    Args:
        previous_start: Inclusive earlier local start date.
        previous_end: Inclusive earlier local end date.
        previous_total: All recorded plays in the earlier period.
        current_total: All recorded plays in the selected period.
        previous_covered: Whether source coverage starts before the earlier period.
        items: Top 15 artists by combined plays, with explicit shares.
    """

    previous_start: date
    previous_end: date
    previous_total: int
    current_total: int
    previous_covered: bool
    items: tuple[ListeningChange, ...]
