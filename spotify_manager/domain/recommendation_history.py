"""Listening history statistics and deterministic weekly recommendation ranking."""

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import timedelta
from typing import cast

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.titles import without_sliding_qualifiers


type TrackKey = tuple[str, str]
DAY_MS = 86400000


@dataclass(frozen=True)
class TrackHistory:
    """Aggregated listening statistics for one normalized track.

    Args:
        artist: Display artist from the first play at the newest timestamp.
        track: Display track from that same play.
        key: Edition-tolerant artist and track identity.
        play_count: All-time play count.
        recent_play_count: Plays inside the inclusive 90-day window.
        annual_play_count: Plays inside the inclusive 365-day window.
        last_played_ms: Latest valid play's original millisecond timestamp.
    """

    artist: str
    track: str
    key: TrackKey
    play_count: int
    recent_play_count: int
    annual_play_count: int
    last_played_ms: int


def canonical_track_key(artist: str, track: str) -> TrackKey:
    """Build the edition-tolerant identity used for heard-track filtering.

    Args:
        artist: Original artist name.
        track: Original track title.

    Returns:
        Normalized artist and qualifier-free track identities.
    """
    return normalize_name(artist), normalize_name(without_sliding_qualifiers(track))


def listening_week_start(local_date: date) -> date:
    """Return the Friday that starts an already-resolved local listening date.

    Args:
        local_date: Effective Berlin-local calendar date.

    Returns:
        The preceding or same-day Friday.
    """
    return local_date - timedelta(days=(local_date.weekday() - 4) % 7)


def weekly_unit_interval(week_start: date, namespace: str, key: TrackKey) -> float:
    """Map a week, ranking namespace and track identity to a stable positive fraction.

    Args:
        week_start: Effective listening week's Friday.
        namespace: Existing distinct ranking context.
        key: Original normalized track identity.

    Returns:
        Original eight-byte BLAKE2 fraction between zero and one.
    """
    payload = "\0".join((week_start.isoformat(), namespace, *key)).encode()
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    integer = int.from_bytes(digest, byteorder="big")
    return (integer + 1) / ((2**64) + 1)


def weekly_weighted_rank(
    week_start: date, namespace: str, key: TrackKey, weight: float
) -> float:
    """Apply the original deterministic weighted-sampling exponent.

    Args:
        week_start: Effective listening week's Friday.
        namespace: Existing ranking context.
        key: Normalized track identity.
        weight: Existing positive sampling weight, floored at one millionth.

    Returns:
        Original weighted fraction; higher values rank first.
    """
    fraction = weekly_unit_interval(week_start, namespace, key)
    return cast(float, fraction ** (1 / max(weight, 0.000001)))


@dataclass
class _TrackCounts:
    """Accumulate occurrence counts while retaining first-seen identity order.

    Args:
        total: All-time counts in first-encountered identity order.
        recent: Inclusive recent-window counts.
        annual: Inclusive annual-window counts.
        display: Newest original display timestamp, artist and title per identity.
    """

    total: Counter[TrackKey] = field(default_factory=Counter)
    recent: Counter[TrackKey] = field(default_factory=Counter)
    annual: Counter[TrackKey] = field(default_factory=Counter)
    display: dict[TrackKey, tuple[int, str, str]] = field(default_factory=dict)

    def record(
        self, scrobble: Scrobble, recent_cutoff: int, annual_cutoff: int
    ) -> None:
        key = canonical_track_key(scrobble.artist, scrobble.track)
        if not all(key):
            return
        self.total[key] += 1
        if scrobble.timestamp_ms >= recent_cutoff:
            self.recent[key] += 1
        if scrobble.timestamp_ms >= annual_cutoff:
            self.annual[key] += 1
        current = self.display.get(key)
        if current is None or scrobble.timestamp_ms > current[0]:
            self.display[key] = (scrobble.timestamp_ms, scrobble.artist, scrobble.track)

    def tracks(self) -> tuple[TrackHistory, ...]:
        """Project accumulated counts in first-encountered identity order.

        Returns:
            Immutable listening statistics with the retained display names.
        """
        tracks = []
        for key, count in self.total.items():
            timestamp, artist, track = self.display[key]
            tracks.append(
                TrackHistory(
                    artist,
                    track,
                    key,
                    count,
                    self.recent[key],
                    self.annual[key],
                    timestamp,
                )
            )
        return tuple(tracks)


def aggregate_track_history(scrobbles: Iterable[Scrobble]) -> tuple[TrackHistory, ...]:
    """Count all-time, annual and recent plays using the newest input as the anchor.

    Args:
        scrobbles: Ordered plays, including invalid normalized identities.

    Returns:
        Valid identities in first-encountered order, with original display tie rules.
    """
    materialized = list(scrobbles)
    if not materialized:
        return ()
    latest = max(scrobble.timestamp_ms for scrobble in materialized)
    recent_cutoff = latest - 90 * DAY_MS
    annual_cutoff = latest - 365 * DAY_MS
    counts = _TrackCounts()
    for scrobble in materialized:
        counts.record(scrobble, recent_cutoff, annual_cutoff)
    return counts.tracks()
