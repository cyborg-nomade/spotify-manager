"""Group selected observations by explicit gaps in recorded UTC timestamps."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from statistics import median
from typing import Literal

from spotify_manager.domain.listening_session_values import ListeningSession
from spotify_manager.domain.listening_session_values import ListeningSessions
from spotify_manager.domain.listening_session_values import SessionBucket
from spotify_manager.domain.listening_session_values import SessionOptions
from spotify_manager.domain.listening_session_values import SessionSize
from spotify_manager.domain.listening_session_values import SessionSummary
from spotify_manager.domain.listening_session_values import SessionWindow
from spotify_manager.domain.listening_time import bucket_name
from spotify_manager.domain.listening_time import bucket_names
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankedEntity


@dataclass
class _Group:
    first_ms: int
    last_ms: int
    artists: Counter[str] = field(default_factory=Counter)
    names: dict[str, str] = field(default_factory=dict)
    tracks: set[str] = field(default_factory=set)

    def add(self, play: ArtistPlay) -> None:
        self.last_ms = play.timestamp_ms
        self.artists[play.artist_key] += 1
        self.names.setdefault(play.artist_key, play.artist_name)
        self.tracks.add(play.track_key)

    def result(self) -> ListeningSession:
        key, count = self.artists.most_common(1)[0]
        plays = self.artists.total()
        artist = RankedEntity(
            key, self.names[key], self.names[key], count, count / plays
        )
        return ListeningSession(
            SessionWindow(self.first_ms, self.last_ms),
            plays,
            len(self.artists),
            len(self.tracks),
            artist,
        )


def _append_group(result: list[ListeningSession], group: _Group | None) -> None:
    if group is not None:
        result.append(group.result())


def group_listening_sessions(
    plays: tuple[ArtistPlay, ...], gap_minutes: int
) -> tuple[ListeningSession, ...]:
    """Partition all selected records without splitting at local midnight.

    Args:
        plays: Chronological observations with stable source-order timestamp ties.
        gap_minutes: Adjacent gaps strictly exceeding this threshold split groups.

    Returns:
        Complete chronological groups; duplicates remain separate recorded rows.
    """
    result: list[ListeningSession] = []
    current: _Group | None = None
    for play in plays:
        if current is None or play.timestamp_ms - current.last_ms > gap_minutes * 60000:
            _append_group(result, current)
            current = _Group(play.timestamp_ms, play.timestamp_ms)
        current.add(play)
    _append_group(result, current)
    if result:
        result[0] = replace(result[0], selection_first=True)
        result[-1] = replace(result[-1], selection_last=True)
    return tuple(result)


def session_summary(
    groups: tuple[ListeningSession, ...], matching: tuple[ListeningSession, ...]
) -> SessionSummary:
    """Keep excluded groups visible in selection coverage.

    Args:
        groups: Every inferred group before the minimum-size filter.
        matching: All groups meeting the minimum size, before pagination.

    Returns:
        Reconciled record/group counts and medians of matching groups.
    """
    plays = [group.plays for group in matching]
    spans = [group.window.last_ms - group.window.first_ms for group in matching]
    return SessionSummary(
        sum(group.plays for group in groups),
        len(groups),
        sum(plays),
        len(matching),
        float(median(plays)) if plays else 0.0,
        float(median(spans)) if spans else 0.0,
    )


def session_buckets(
    groups: tuple[ListeningSession, ...], query: ListeningQuery, grain: str
) -> tuple[SessionBucket, ...]:
    """Attribute each complete selected group to its first record's local bucket.

    Args:
        groups: Matching groups before pagination.
        query: Local dates and display timezone.
        grain: Monday-based week or calendar month.

    Returns:
        Every bucket, including empty periods, with exact groups and rows.
    """
    counts: Counter[str] = Counter()
    plays: Counter[str] = Counter()
    for group in groups:
        day = local_instant(group.window.first_ms, query.timezone).date()
        label = bucket_name(day, grain)
        counts[label] += 1
        plays[label] += group.plays
    result = []
    for label in bucket_names(query, grain):
        result.append(SessionBucket(label, counts[label], plays[label]))
    return tuple(result)


def session_sizes(groups: tuple[ListeningSession, ...]) -> tuple[SessionSize, ...]:
    """Partition matching groups into six disjoint recorded-row size bands.

    Args:
        groups: Complete matching groups independent of pagination.

    Returns:
        Fixed size bands conserving every matching group and recorded row.
    """
    counts: Counter[int] = Counter()
    plays: Counter[int] = Counter()
    for group in groups:
        band = _size_band(group.plays)
        counts[band] += 1
        plays[band] += group.plays
    labels = ("1", "2–5", "6–10", "11–25", "26–50", "51+")
    result = []
    for index, label in enumerate(labels):
        result.append(SessionSize(label, counts[index], plays[index]))
    return tuple(result)


def _size_band(plays: int) -> int:
    for index, maximum in enumerate((1, 5, 10, 25, 50)):
        if plays <= maximum:
            return index
    return 5


def _recent_order(group: ListeningSession) -> int:
    return -group.window.first_ms


def _play_order(group: ListeningSession) -> tuple[int, int]:
    return -group.plays, -group.window.first_ms


def listening_sessions(
    groups: tuple[ListeningSession, ...], query: ListeningQuery, options: SessionOptions
) -> ListeningSessions:
    """Present matching groups and charts without changing their inference rules.

    Args:
        groups: Complete chronological groups for this exact selection and gap.
        query: Shared dates, timezone and artist/rhythm filters.
        options: Minimum size, ordering and bounded page.

    Returns:
        One group page and complete matching scope, chart buckets and size bands.
    """
    matching = tuple(group for group in groups if group.plays >= options.minimum_plays)
    # sorted requires a key function; these fixed projections are not dependencies.
    ordered = sorted(
        matching, key=_play_order if options.order == "plays" else _recent_order
    )
    offset = (options.page - 1) * options.limit
    grain: Literal["week", "month"] = (
        "week" if (query.end - query.start).days <= 180 else "month"
    )
    return ListeningSessions(
        tuple(ordered[offset : offset + options.limit]),
        session_summary(groups, matching),
        options,
        grain,
        session_buckets(matching, query, grain),
        session_sizes(matching),
    )
