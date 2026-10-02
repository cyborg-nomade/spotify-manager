"""Original artist history, seed and recommendation business values."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ArtistHistory:
    """Aggregated Last.fm listening history for one artist.

    Args:
        artist: Original newest display spelling.
        key: Original normalized artist identity.
        play_count: Original all-time play count.
        recent_play_count: Original inclusive 90-day count.
        annual_play_count: Original inclusive 365-day count.
        last_played_ms: Original newest play timestamp.
    """

    artist: str
    key: str
    play_count: int
    recent_play_count: int
    annual_play_count: int
    last_played_ms: int


@dataclass(frozen=True)
class ArtistSeed:
    """One history artist used for Last.fm neighbor discovery.

    Args:
        artist: Original history display name.
        key: Original normalized identity.
        source: Original recent, annual or overall quota.
        play_count: Original all-time play count.
        source_play_count: Original quota metric count.
        weight: Original neighbor-score multiplier.
        weekly_rank: Original deterministic weekly sampling rank.
    """

    artist: str
    key: str
    source: Literal["recent", "annual", "overall"]
    play_count: int
    source_play_count: int
    weight: float
    weekly_rank: float


@dataclass(frozen=True)
class ArtistRecommendation:
    """One unheard artist aggregated from Last.fm seed neighborhoods.

    Args:
        artist: Original first neighbor display spelling.
        key: Original normalized neighbor identity.
        score: Original seed-weighted support score.
        best_match: Original maximum observed neighbor match.
        supporting_seeds: Original sorted unique supporting display names.
        base_rank: Original score-order rank before weekly rotation.
        weekly_rank: Original deterministic rotation rank.
    """

    artist: str
    key: str
    score: float
    best_match: float
    supporting_seeds: tuple[str, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0
