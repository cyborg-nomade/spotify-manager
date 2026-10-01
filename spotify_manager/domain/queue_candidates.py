"""Combine artist neighborhoods and preserve The Queue's weekly rotation."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import date

from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.domain.recommendation_history import weekly_weighted_rank


@dataclass(frozen=True)
class LastFmSimilarArtist:
    """One observed artist in a Last.fm neighborhood.

    Args:
        artist: Original display spelling.
        match: Original similarity score.
    """

    artist: str
    match: float


@dataclass
class _ArtistAccumulator:
    """Retain first display spelling and distinct original seed labels.

    Args:
        artist: First observed artist spelling.
        key: Original normalized identity.
        score: Combined weighted similarities.
        best_match: Greatest similarity, with the original zero floor.
        supporting_seeds: Distinct raw seed labels.
    """

    artist: str
    key: str
    score: float = 0.0
    best_match: float = 0.0
    supporting_seeds: set[str] = field(default_factory=set)


def _base_key(candidate: ArtistRecommendation) -> tuple[float, int, float, str]:
    return (
        -candidate.score,
        -len(candidate.supporting_seeds),
        -candidate.best_match,
        candidate.key,
    )


def _weekly_key(candidate: ArtistRecommendation) -> tuple[float, int, str]:
    return -candidate.weekly_rank, candidate.base_rank, candidate.key


def _recommendation(candidate: _ArtistAccumulator) -> ArtistRecommendation:
    support = tuple(sorted(candidate.supporting_seeds))
    return ArtistRecommendation(
        candidate.artist,
        candidate.key,
        candidate.score * (1 + 0.15 * (len(support) - 1)),
        candidate.best_match,
        support,
    )


@dataclass
class QueueCandidates:
    """Aggregate unheard artists after neighborhood cache checkpoints succeed.

    Args:
        excluded: Heard or previously added normalized identities.
        candidates: Observations in original first-identity order.
    """

    excluded: set[str]
    candidates: dict[str, _ArtistAccumulator] = field(default_factory=dict)

    def observe(
        self, seed: ArtistSeed, similar: tuple[LastFmSimilarArtist, ...]
    ) -> None:
        """Combine one neighborhood while retaining original duplicate semantics.

        Args:
            seed: Original seed weight and display label.
            similar: Ordered neighbor observations.
        """
        for neighbor in similar:
            key = normalize_name(neighbor.artist)
            if not key or key in self.excluded:
                continue
            candidate = self.candidates.setdefault(
                key, _ArtistAccumulator(neighbor.artist, key)
            )
            candidate.score += seed.weight * neighbor.match
            candidate.best_match = max(candidate.best_match, neighbor.match)
            candidate.supporting_seeds.add(seed.artist)

    def ranked(self, week: date, limit: int) -> tuple[ArtistRecommendation, ...]:
        """Apply the original support bonus, pool slice and weekly ranking.

        Args:
            week: Original effective listening week.
            limit: Original slice limit, including zero and negative values.

        Returns:
            Rotated candidates with original base ranks and scores.
        """
        candidates = [_recommendation(value) for value in self.candidates.values()]
        pool = sorted(candidates, key=_base_key)[:limit]
        rotated: list[ArtistRecommendation] = []
        for rank, candidate in enumerate(pool, start=1):
            rotated.append(
                replace(
                    candidate,
                    base_rank=rank,
                    weekly_rank=weekly_weighted_rank(
                        week, "queue-candidate", (candidate.key, ""), candidate.score**2
                    ),
                )
            )
        return tuple(sorted(rotated, key=_weekly_key))
