"""Fixed-membership artist trajectories and recorded listening breadth."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from spotify_manager.domain.listening_time import bucket_name
from spotify_manager.domain.listening_time import bucket_names
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningBreadth
from spotify_manager.domain.listening_values import ListeningEvolution
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningSeries


@dataclass
class _Bucket:
    artists: Counter[str] = field(default_factory=Counter)
    tracks: set[str] = field(default_factory=set)

    def add(self, play: ArtistPlay) -> None:
        self.artists[play.artist_key] += 1
        self.tracks.add(play.track_key)

    def breadth(self) -> ListeningBreadth:
        total = self.artists.total()
        maximum = max(self.artists.values(), default=0)
        return ListeningBreadth(
            len(self.artists), len(self.tracks), maximum / total if total else 0
        )


@dataclass
class _Evolution:
    buckets: dict[str, _Bucket] = field(default_factory=dict)
    totals: Counter[str] = field(default_factory=Counter)
    names: dict[str, str] = field(default_factory=dict)

    def add(self, play: ArtistPlay, query: ListeningQuery, grain: str) -> None:
        day = local_instant(play.timestamp_ms, query.timezone).date()
        name = bucket_name(day, grain)
        self.buckets.setdefault(name, _Bucket()).add(play)
        self.totals[play.artist_key] += 1
        self.names[play.artist_key] = play.artist_name

    def series(self, names: tuple[str, ...]) -> tuple[ListeningSeries, ...]:
        selected = self.totals.most_common(8)
        result = []
        for key, _count in selected:
            counts = self._counts(names, key)
            result.append(ListeningSeries(key, self.names[key], counts))
        other = self._other(names, set(dict(selected)))
        result.append(ListeningSeries("other", "Other", other))
        return tuple(result)

    def _counts(self, names: tuple[str, ...], key: str) -> tuple[int, ...]:
        result = []
        for name in names:
            result.append(self.buckets.get(name, _Bucket()).artists[key])
        return tuple(result)

    def _other(self, names: tuple[str, ...], selected: set[str]) -> tuple[int, ...]:
        result = []
        for name in names:
            counts = self.buckets.get(name, _Bucket()).artists
            remainder = counts.total()
            for key in selected:
                remainder -= counts[key]
            result.append(remainder)
        return tuple(result)


def listening_evolution(
    plays: tuple[ArtistPlay, ...],
    query: ListeningQuery,
    grain: Literal["week", "month"],
) -> ListeningEvolution:
    """Keep eight selected artists and Other stable throughout the date range.

    Args:
        plays: Exact filtered observations.
        query: Local calendar interval.
        grain: Weekly or monthly aggregation.

    Returns:
        Aligned series and per-bucket breadth, including empty buckets.
    """
    evolution = _Evolution()
    for play in plays:
        evolution.add(play, query, grain)
    names = bucket_names(query, grain)
    breadth = []
    for name in names:
        breadth.append(evolution.buckets.get(name, _Bucket()).breadth())
    return ListeningEvolution(names, evolution.series(names), tuple(breadth), grain)
