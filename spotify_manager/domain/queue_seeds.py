"""Select original recent, annual and overall artist quotas with weekly rotation."""

import math
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from functools import partial
from typing import Literal

from spotify_manager.domain.queue_values import ArtistHistory
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.domain.recommendation_history import weekly_weighted_rank


type SeedSource = Literal["recent", "annual", "overall"]
type SeedMetric = Literal["recent_play_count", "annual_play_count", "play_count"]
type RankedArtist = tuple[float, ArtistHistory]
SPECS: tuple[tuple[SeedSource, SeedMetric, float], ...] = (
    ("recent", "recent_play_count", 1.25),
    ("annual", "annual_play_count", 1.10),
    ("overall", "play_count", 1.00),
)


def _metric(artist: ArtistHistory, metric: SeedMetric) -> int:
    if metric == "recent_play_count":
        return int(artist.recent_play_count)
    if metric == "annual_play_count":
        return int(artist.annual_play_count)
    return int(artist.play_count)


def _popular_order(
    metric: SeedMetric, artist: ArtistHistory
) -> tuple[int, int, int, str]:
    return (
        -_metric(artist, metric),
        -artist.play_count,
        -artist.last_played_ms,
        artist.key,
    )


def _weekly_order(item: RankedArtist) -> tuple[float, str]:
    rank, artist = item
    return -rank, artist.key


def _rank_group(
    pool: list[ArtistHistory], source: SeedSource, metric: SeedMetric, week: date
) -> list[RankedArtist]:
    ranked: list[RankedArtist] = []
    for artist in pool:
        rank = weekly_weighted_rank(
            week,
            f"queue-seed:{source}",
            (artist.key, ""),
            math.log1p(_metric(artist, metric)),
        )
        ranked.append((rank, artist))
    return sorted(ranked, key=_weekly_order)


def _fallback_order(week: date, artist: ArtistHistory) -> tuple[float, str]:
    return (
        -weekly_weighted_rank(
            week, "queue-seed:fallback", (artist.key, ""), math.log1p(artist.play_count)
        ),
        artist.key,
    )


def _seed(
    artist: ArtistHistory, source: SeedSource, count: int, weight: float, rank: float
) -> ArtistSeed:
    return ArtistSeed(
        artist.artist,
        artist.key,
        source,
        artist.play_count,
        count,
        weight * (1 + min(math.log1p(count), 6.0) / 10),
        rank,
    )


@dataclass
class _SeedSelection:
    """Accumulate quota seeds and exclude their identities from later groups.

    Args:
        artists: Original history observations.
        week: Original effective listening week.
        pool_multiplier: Original candidate pool multiplier.
        selected: Original ordered accepted seeds.
        used: Identities represented in completed quota groups.
    """

    artists: tuple[ArtistHistory, ...]
    week: date
    pool_multiplier: int
    selected: list[ArtistSeed] = field(default_factory=list)
    used: set[str] = field(default_factory=set)

    def group(
        self, source: SeedSource, metric: SeedMetric, weight: float, quota: int
    ) -> None:
        """Apply a quota using original popularity truncation and weekly ordering.

        Args:
            source: Original quota identity.
            metric: Original history-count field.
            weight: Original neighbor-score multiplier.
            quota: Original number of seeds for this group.
        """
        pool: list[ArtistHistory] = []
        for artist in self.artists:
            if artist.key not in self.used and _metric(artist, metric) > 0:
                pool.append(artist)
        pool.sort(key=partial(_popular_order, metric))
        pool = pool[: max(quota, quota * self.pool_multiplier)]
        ranked = _rank_group(pool, source, metric, self.week)
        for rank, artist in ranked[:quota]:
            self.selected.append(
                _seed(artist, source, _metric(artist, metric), weight, rank)
            )
            self.used.add(artist.key)

    def fallback(self, remaining: int) -> None:
        """Fill an unmet quota from unused original history observations.

        Args:
            remaining: Original remaining seed slots.
        """
        pool: list[ArtistHistory] = []
        for artist in self.artists:
            if artist.key not in self.used:
                pool.append(artist)
        pool.sort(key=partial(_fallback_order, self.week))
        for artist in pool[:remaining]:
            rank = weekly_weighted_rank(
                self.week,
                "queue-seed:fallback",
                (artist.key, ""),
                math.log1p(artist.play_count),
            )
            self.selected.append(_seed(artist, "overall", artist.play_count, 1.0, rank))


def select_seeds(
    artists: tuple[ArtistHistory, ...],
    count: int,
    week: date,
    pool_multiplier: int = 10,
) -> tuple[ArtistSeed, ...]:
    """Apply original quota and fallback selection to already validated seed inputs.

    Args:
        artists: Original history facts in observation order.
        count: Original validated requested seed count.
        week: Original effective listening week.
        pool_multiplier: Original per-quota candidate pool multiplier.

    Returns:
        Original ordered weekly artist seeds, retaining duplicate-input behavior.
    """
    selection = _SeedSelection(artists, week, pool_multiplier)
    base, remainder = divmod(count, len(SPECS))
    for index, (source, metric, weight) in enumerate(SPECS):
        selection.group(source, metric, weight, base + (1 if index < remainder else 0))
    if len(selection.selected) < count:
        selection.fallback(count - len(selection.selected))
    return tuple(selection.selected)
