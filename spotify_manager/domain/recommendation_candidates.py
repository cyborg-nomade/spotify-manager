"""Aggregate unheard recommendation neighborhoods and preserve weekly ranking."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import date

from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_history import canonical_track_key
from spotify_manager.domain.recommendation_history import weekly_weighted_rank
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


@dataclass(frozen=True)
class LastFmSimilarTrack:
    """One track observed in a Last.fm recommendation neighborhood.

    Args:
        artist: Original neighbor artist name.
        track: Original neighbor title.
        match: Original Last.fm similarity score.
    """

    artist: str
    track: str
    match: float


@dataclass(frozen=True)
class FoundArtCandidate:
    """One unheard candidate aggregated across seed recommendations.

    Args:
        artist: First encountered neighbor artist spelling.
        track: First encountered neighbor title spelling.
        key: Edition-tolerant artist/title identity.
        score: Weighted support score with the original distinct-seed bonus.
        best_match: Highest observed similarity, starting at zero.
        supporting_seeds: Sorted distinct original seed labels.
        base_rank: One-based original rank within the limited candidate pool.
        weekly_rank: Original deterministic weighted weekly score.
    """

    artist: str
    track: str
    key: TrackKey
    score: float
    best_match: float
    supporting_seeds: tuple[str, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0


@dataclass
class _CandidateAccumulator:
    """Mutable aggregation state while seed neighborhoods are combined.

    Args:
        artist: First observed display artist.
        track: First observed display title.
        key: Original normalized identity.
        score: Accumulated seed-weighted similarities.
        best_match: Highest observed similarity, starting at zero.
        supporting_seeds: Original distinct seed labels, initialized when absent.
    """

    artist: str
    track: str
    key: TrackKey
    score: float = 0.0
    best_match: float = 0.0
    supporting_seeds: set[str] | None = None

    def __post_init__(self) -> None:
        """Initialize support storage while preserving an explicitly supplied set."""
        if self.supporting_seeds is None:
            self.supporting_seeds = set()


def _base_key(candidate: FoundArtCandidate) -> tuple[float, int, float, TrackKey]:
    return (
        -candidate.score,
        -len(candidate.supporting_seeds),
        -candidate.best_match,
        candidate.key,
    )


def _weekly_key(candidate: FoundArtCandidate) -> tuple[float, int, TrackKey]:
    return -candidate.weekly_rank, candidate.base_rank, candidate.key


def _candidate(accumulator: _CandidateAccumulator) -> FoundArtCandidate:
    support = tuple(sorted(accumulator.supporting_seeds or ()))
    return FoundArtCandidate(
        accumulator.artist,
        accumulator.track,
        accumulator.key,
        accumulator.score * (1 + 0.15 * (len(support) - 1)),
        accumulator.best_match,
        support,
    )


@dataclass
class RecommendationCandidates:
    """Retain first display spelling and combine all eligible seed support.

    Args:
        excluded: Heard or previously added identities.
        candidates: Accumulated candidates in first-encountered order.
    """

    excluded: set[TrackKey]
    candidates: dict[TrackKey, _CandidateAccumulator] = field(default_factory=dict)

    def observe(
        self, seed: FoundArtSeed, similar: tuple[LastFmSimilarTrack, ...]
    ) -> None:
        """Combine one neighborhood after its cache checkpoint has succeeded.

        Args:
            seed: Original weighted seed and display label.
            similar: Original ordered neighborhood observations.

        Raises:
            AssertionError: An accumulator's initialized support set is corrupted.
        """
        label = f"{seed.artist} - {seed.track}"
        for neighbor in similar:
            key = canonical_track_key(neighbor.artist, neighbor.track)
            if not all(key) or key in self.excluded:
                continue
            candidate = self.candidates.setdefault(
                key, _CandidateAccumulator(neighbor.artist, neighbor.track, key)
            )
            candidate.score += seed.weight * neighbor.match
            candidate.best_match = max(candidate.best_match, neighbor.match)
            if candidate.supporting_seeds is None:
                raise AssertionError("candidate support set was not initialized")
            candidate.supporting_seeds.add(label)

    def ranked(self, week: date, limit: int) -> tuple[FoundArtCandidate, ...]:
        """Apply support bonus, base pool limits and the original weekly rotation.

        Args:
            week: Effective listening week.
            limit: Original maximum candidate pool size.

        Returns:
            Rotated candidates with original base ranks and weekly scores.
        """
        candidates = [_candidate(candidate) for candidate in self.candidates.values()]
        pool = sorted(candidates, key=_base_key)[:limit]
        rotated = []
        for rank, candidate in enumerate(pool, start=1):
            rotated.append(
                replace(
                    candidate,
                    base_rank=rank,
                    weekly_rank=weekly_weighted_rank(
                        week, "candidate", candidate.key, candidate.score**2
                    ),
                )
            )
        return tuple(sorted(rotated, key=_weekly_key))
