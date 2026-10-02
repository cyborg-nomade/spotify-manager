"""Weekly seed selection from recent, annual and overall listening statistics."""

import math
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from functools import partial
from typing import Literal

from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_history import weekly_weighted_rank


type SeedSource = Literal["recent", "annual", "overall"]
type RankedTrack = tuple[float, TrackHistory]


@dataclass(frozen=True)
class FoundArtSeed:
    """One known track used to ask Last.fm for neighbors.

    Args:
        artist: Original display artist retained by history aggregation.
        track: Original display title.
        key: Edition-tolerant artist/title identity.
        source: Recent, annual or overall quota responsible for selection.
        play_count: All-time plays from the original history.
        source_play_count: Plays used by the source quota's ranking.
        weight: Original source-weighted recommendation contribution.
        weekly_rank: Deterministic weekly selection score.
    """

    artist: str
    track: str
    key: TrackKey
    source: Literal["recent", "annual", "overall"]
    play_count: int
    source_play_count: int
    weight: float
    weekly_rank: float = 1.0


def _metric(track: TrackHistory, source: SeedSource) -> int:
    if source == "recent":
        return track.recent_play_count
    if source == "annual":
        return track.annual_play_count
    return track.play_count


def _popular_key(
    source: SeedSource, track: TrackHistory
) -> tuple[int, int, int, TrackKey]:
    return (
        -int(_metric(track, source)),
        -track.play_count,
        -track.last_played_ms,
        track.key,
    )


def _weekly_key(source: SeedSource, item: RankedTrack) -> tuple[float, int, TrackKey]:
    rank, track = item
    return -rank, -int(_metric(track, source)), track.key


def _fallback_popular_key(track: TrackHistory) -> tuple[int, int, TrackKey]:
    return -track.play_count, -track.last_played_ms, track.key


def _fallback_weekly_key(item: RankedTrack) -> tuple[float, int, TrackKey]:
    rank, track = item
    return -rank, -track.play_count, track.key


def _group_pool(
    tracks: tuple[TrackHistory, ...],
    source: SeedSource,
    used: set[TrackKey],
    limit: int,
) -> list[TrackHistory]:
    pool = []
    for track in tracks:
        if _metric(track, source) > 0 and track.key not in used:
            pool.append(track)
    return sorted(pool, key=partial(_popular_key, source))[:limit]


def _rank_group(
    pool: list[TrackHistory], source: SeedSource, week: date
) -> list[RankedTrack]:
    ranked = []
    for track in pool:
        rank = weekly_weighted_rank(
            week, f"seed:{source}", track.key, math.log1p(int(_metric(track, source)))
        )
        ranked.append((rank, track))
    return sorted(ranked, key=partial(_weekly_key, source))


def _rank_fallback(
    tracks: tuple[TrackHistory, ...], used: set[TrackKey], remaining: int, week: date
) -> list[RankedTrack]:
    pool = []
    for track in tracks:
        if track.key not in used:
            pool.append(track)
    pool = sorted(pool, key=_fallback_popular_key)[: max(1000, remaining * 100)]
    ranked = []
    for track in pool:
        rank = weekly_weighted_rank(
            week, "seed:overall:fallback", track.key, math.log1p(track.play_count)
        )
        ranked.append((rank, track))
    return sorted(ranked, key=_fallback_weekly_key)


@dataclass
class _SeedSelection:
    """Track accepted seeds and the original per-artist diversity limit.

    Args:
        max_per_artist: Original allowed seeds per normalized artist.
        selected: Accepted seeds in group and fallback order.
        used: Accepted identities excluded from subsequent pools.
        artist_counts: Accepted occurrence counts per normalized artist.
    """

    max_per_artist: int
    selected: list[FoundArtSeed] = field(default_factory=list)
    used: set[TrackKey] = field(default_factory=set)
    artist_counts: Counter[str] = field(default_factory=Counter)

    def accept(
        self,
        track: TrackHistory,
        source: SeedSource,
        source_count: int,
        base_weight: float,
        rank: float,
    ) -> bool:
        """Accept a seed when the artist cap permits it.

        Args:
            track: Selected history record, including original duplicate tolerance.
            source: Quota or fallback source.
            source_count: Original source-specific play count.
            base_weight: Original recommendation contribution weight.
            rank: Original deterministic weekly rank.

        Returns:
            Whether the seed was accepted and counted toward its artist cap.
        """
        artist_key = track.key[0]
        if self.artist_counts[artist_key] >= self.max_per_artist:
            return False
        weight = base_weight * (1 + min(math.log1p(source_count), 6.0) / 10)
        self.selected.append(
            FoundArtSeed(
                track.artist,
                track.track,
                track.key,
                source,
                track.play_count,
                source_count,
                weight,
                rank,
            )
        )
        self.used.add(track.key)
        self.artist_counts[artist_key] += 1
        return True


def _add_group(
    selection: _SeedSelection,
    tracks: tuple[TrackHistory, ...],
    source: SeedSource,
    base_weight: float,
    quota: int,
    count: int,
    week: date,
    multiplier: int,
) -> None:
    if quota == 0:
        return
    pool = _group_pool(tracks, source, selection.used, quota * multiplier)
    added = 0
    for rank, track in _rank_group(pool, source, week):
        if not selection.accept(
            track, source, int(_metric(track, source)), base_weight, rank
        ):
            continue
        added += 1
        if added >= quota or len(selection.selected) >= count:
            break


def _fill(
    selection: _SeedSelection, tracks: tuple[TrackHistory, ...], count: int, week: date
) -> None:
    remaining = count - len(selection.selected)
    for rank, track in _rank_fallback(tracks, selection.used, remaining, week):
        if not selection.accept(track, "overall", track.play_count, 1.0, rank):
            continue
        if len(selection.selected) >= count:
            break


def choose_seeds(
    tracks: tuple[TrackHistory, ...],
    count: int,
    week: date,
    pool_multiplier: int = 10,
    max_per_artist: int = 2,
) -> tuple[FoundArtSeed, ...]:
    """Choose recent/annual/overall quotas and fill gaps with the original weekly pool.

    Args:
        tracks: Original ordered history; callers validate nonempty input.
        count: Positive requested seed count, validated by the application.
        week: Effective listening week.
        pool_multiplier: Original popularity pool size per group quota.
        max_per_artist: Original maximum selected seeds per normalized artist.

    Returns:
        Best available seeds in group and fallback order; possibly fewer than count.
    """
    groups: tuple[tuple[SeedSource, float], ...] = (
        ("recent", 1.25),
        ("annual", 1.10),
        ("overall", 1.00),
    )
    base_quota, remainder = divmod(count, len(groups))
    selection = _SeedSelection(max_per_artist)
    for index, (source, base_weight) in enumerate(groups):
        quota = base_quota + int(index < remainder)
        _add_group(
            selection, tracks, source, base_weight, quota, count, week, pool_multiplier
        )
    if len(selection.selected) < count:
        _fill(selection, tracks, count, week)
    return tuple(selection.selected)
