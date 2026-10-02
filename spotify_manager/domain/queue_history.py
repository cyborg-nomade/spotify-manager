"""Aggregate original artist seed windows anchored to the latest observed play."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.queue_values import ArtistHistory


@dataclass
class _ArtistCounts:
    """Accumulate counts while preserving original first-identity display order.

    Args:
        total: Original all-time counts.
        recent: Original inclusive 90-day counts.
        annual: Original inclusive 365-day counts.
        display: Newest original timestamp and first spelling on tied timestamps.
    """

    total: Counter[str] = field(default_factory=Counter)
    recent: Counter[str] = field(default_factory=Counter)
    annual: Counter[str] = field(default_factory=Counter)
    display: dict[str, tuple[int, str]] = field(default_factory=dict)

    def record(
        self, scrobble: Scrobble, recent_cutoff: int, annual_cutoff: int
    ) -> None:
        """Record a play using the original normalized artist and inclusive cutoffs.

        Args:
            scrobble: Original play.
            recent_cutoff: Original inclusive recent-window start.
            annual_cutoff: Original inclusive annual-window start.
        """
        key = normalize_name(scrobble.artist)
        if not key:
            return
        self.total[key] += 1
        if scrobble.timestamp_ms >= recent_cutoff:
            self.recent[key] += 1
        if scrobble.timestamp_ms >= annual_cutoff:
            self.annual[key] += 1
        previous = self.display.get(key)
        if previous is None or scrobble.timestamp_ms > previous[0]:
            self.display[key] = scrobble.timestamp_ms, scrobble.artist

    def result(self) -> tuple[ArtistHistory, ...]:
        """Build original artist facts in first-identity occurrence order.

        Returns:
            Original artist history observations.
        """
        artists: list[ArtistHistory] = []
        for key, count in self.total.items():
            artists.append(
                ArtistHistory(
                    self.display[key][1],
                    key,
                    count,
                    self.recent[key],
                    self.annual[key],
                    self.display[key][0],
                )
            )
        return tuple(artists)


def aggregate_artists(scrobbles: Iterable[Scrobble]) -> tuple[ArtistHistory, ...]:
    """Preserve first-identity order, inclusive windows and newest-display ties.

    Args:
        scrobbles: Original plays, including blank names that still anchor the window.

    Returns:
        Original artist counts in first-identity occurrence order.
    """
    plays = list(scrobbles)
    if not plays:
        return ()
    latest = max(play.timestamp_ms for play in plays)
    recent_cutoff = latest - int(timedelta(days=90).total_seconds() * 1000)
    annual_cutoff = latest - int(timedelta(days=365).total_seconds() * 1000)
    counts = _ArtistCounts()
    for play in plays:
        counts.record(play, recent_cutoff, annual_cutoff)
    return counts.result()
