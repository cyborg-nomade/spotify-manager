"""Pure neighborhood aggregation, support bonuses and weekly candidate rotation."""

from datetime import date

import pytest

from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_candidates import RecommendationCandidates
from spotify_manager.domain.recommendation_candidates import _CandidateAccumulator
from spotify_manager.domain.recommendation_history import weekly_weighted_rank
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


WEEK = date(2026, 7, 17)


def _seed(title: str, weight: float = 1.0) -> FoundArtSeed:
    return FoundArtSeed("Seed", title, ("seed", title), "recent", 10, 5, weight)


def test_aggregation_retains_first_spelling_and_distinct_support_bonus() -> None:
    """Repeated seed labels add score without increasing distinct-label bonuses."""
    candidates = RecommendationCandidates(set())
    candidates.observe(
        _seed("One", 2.0), (LastFmSimilarTrack("Björk", "Song - Remastered", 0.5),)
    )
    candidates.observe(_seed("One", 2.0), (LastFmSimilarTrack("BJORK", "Song", 0.4),))
    candidates.observe(_seed("Two"), (LastFmSimilarTrack("Bjork", "SONG", 1.0),))
    result = candidates.ranked(WEEK, 10)
    assert len(result) == 1
    candidate = result[0]
    assert (candidate.artist, candidate.track, candidate.key) == (
        "Björk",
        "Song - Remastered",
        ("bjork", "song"),
    )
    assert candidate.score == (1.0 + 0.8 + 1.0) * 1.15
    assert candidate.best_match == 1.0
    assert candidate.supporting_seeds == ("Seed - One", "Seed - Two")
    assert candidate.base_rank == 1
    assert candidate.weekly_rank == weekly_weighted_rank(
        WEEK, "candidate", candidate.key, candidate.score**2
    )


def test_heard_logged_and_invalid_keys_are_excluded_before_accumulation() -> None:
    """Keep invalid identities and all supplied exclusions out of candidate support."""
    candidates = RecommendationCandidates({("heard", "song"), ("logged", "song")})
    candidates.observe(
        _seed("One"),
        (
            LastFmSimilarTrack("Heard", "Song", 1.0),
            LastFmSimilarTrack("Logged", "Song", 1.0),
            LastFmSimilarTrack("!!!", "Song", 1.0),
            LastFmSimilarTrack("Artist", "!!!", 1.0),
        ),
    )
    assert candidates.ranked(WEEK, 10) == ()
    assert not candidates.candidates


def test_pool_limit_is_applied_to_base_score_before_weekly_rotation() -> None:
    """Only the strongest base pool is rotated, with original base ranks retained."""
    candidates = RecommendationCandidates(set())
    candidates.observe(
        _seed("One"),
        (
            LastFmSimilarTrack("A", "Song", 3.0),
            LastFmSimilarTrack("B", "Song", 2.0),
            LastFmSimilarTrack("C", "Song", 1.0),
        ),
    )
    result = candidates.ranked(WEEK, 2)
    assert {candidate.key for candidate in result} == {("a", "song"), ("b", "song")}
    assert {candidate.key: candidate.base_rank for candidate in result} == {
        ("a", "song"): 1,
        ("b", "song"): 2,
    }
    ranks = [candidate.weekly_rank for candidate in result]
    assert ranks == sorted(ranks, reverse=True)


def test_base_rank_ties_keep_support_count_best_match_and_key_order() -> None:
    """Original score ties use distinct support, similarity and normalized identity."""
    candidates = RecommendationCandidates(set())
    candidates.candidates = {
        ("z", "song"): _CandidateAccumulator(
            "Z", "Song", ("z", "song"), 2.0, 1.0, {"one"}
        ),
        ("a", "song"): _CandidateAccumulator(
            "A", "Song", ("a", "song"), 2.0, 1.0, {"one"}
        ),
        ("b", "song"): _CandidateAccumulator(
            "B", "Song", ("b", "song"), 2.0, 2.0, {"one"}
        ),
    }
    ranks = {
        candidate.artist: candidate.base_rank
        for candidate in candidates.ranked(WEEK, 10)
    }
    assert ranks == {"B": 1, "A": 2, "Z": 3}


def test_missing_support_and_negative_matches_keep_original_projection() -> None:
    """Empty support uses the original bonus expression and best-match zero floor."""
    candidates = RecommendationCandidates(set())
    candidates.observe(_seed("One"), (LastFmSimilarTrack("Artist", "Song", -1.0),))
    assert candidates.ranked(WEEK, 10)[0].best_match == 0.0
    accumulator = candidates.candidates[("artist", "song")]
    accumulator.supporting_seeds = None
    result = candidates.ranked(WEEK, 10)[0]
    assert result.score == -0.85 and result.supporting_seeds == ()
    with pytest.raises(AssertionError, match="support set was not initialized"):
        candidates.observe(_seed("Two"), (LastFmSimilarTrack("Artist", "Song", 1.0),))
    assert accumulator.score == 0.0 and accumulator.best_match == 1.0
