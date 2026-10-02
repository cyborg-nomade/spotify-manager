"""Historical match qualification and ranking contracts without API dependencies."""

from dataclasses import replace

import pytest

from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import name_similarity
from spotify_manager.domain.history_matching import preferred_match
from spotify_manager.domain.history_matching import qualifying_matches


def _match(identifier: str = "first") -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        identifier,
        f"spotify:track:{identifier}",
        "Track",
        ("Artist",),
        "Album",
        1,
        1.0,
        1.0,
        50,
    )


@pytest.mark.parametrize(
    "expected,candidate,similarity",
    [
        ("Björk", "bjork", 1.0),
        ("Track", "Track - Remastered", 1.0),
        ("", "Track", 0.0),
        ("Track", "!!!", 0.0),
        ("abcd", "abce", 0.75),
    ],
)
def test_similarity_retains_normalization_and_empty_names(
    expected: str, candidate: str, similarity: float
) -> None:
    """Remove recognized qualifiers and punctuation before comparing title sequences.

    Args:
        expected: Export title.
        candidate: Observed title.
        similarity: Expected sequence similarity.
    """
    assert name_similarity(expected, candidate) == similarity


@pytest.mark.parametrize(
    "similarity,liked,accepted",
    [(None, False, True), (0.9, False, True), (0.899, False, False), (0.0, True, True)],
)
def test_liked_status_overrides_only_album_qualification(
    similarity: float | None, liked: bool, accepted: bool
) -> None:
    """Apply inclusive album thresholds with a current liked override.

    Args:
        similarity: Observed album similarity or missing export album.
        liked: Live liked status.
        accepted: Whether the match qualifies.
    """
    observed = replace(_match(), album_similarity=similarity, liked=not liked)
    result = qualifying_matches((observed,), {"first"} if liked else set())
    assert bool(result) is accepted
    assert observed.liked is not liked
    if accepted:
        assert result[0].liked is liked and result[0] is not observed


def test_album_threshold_and_search_order_remain_explicit() -> None:
    """Return all qualifying editions in observed order at the supplied threshold."""
    first = replace(_match(), album_similarity=0.7)
    second = replace(_match("second"), album_similarity=0.8)
    assert qualifying_matches((second, first), set(), 0.7) == (second, first)
    assert qualifying_matches((second, first), set(), 0.81) == ()


@pytest.mark.parametrize(
    "criterion", ["liked", "track", "album", "popularity", "search"]
)
def test_preference_uses_original_ranking_priority(criterion: str) -> None:
    """Prefer each successive ranking field when preceding fields tie.

    Args:
        criterion: Ranking field deciding the result.
    """
    first, second = _match(), _match("second")
    liked: set[str] = set()
    if criterion == "liked":
        second = replace(second, album_similarity=0.0, track_similarity=0.5)
        liked.add("second")
    if criterion == "track":
        first = replace(first, track_similarity=0.95)
    if criterion == "album":
        first = replace(first, album_similarity=0.95)
    if criterion == "popularity":
        second = replace(second, popularity=51)
    if criterion == "search":
        first = replace(first, search_rank=2)
    assert preferred_match((first, second), liked) == replace(second, liked=bool(liked))


def test_missing_album_and_popularity_keep_original_rank_defaults() -> None:
    """Missing album scores as one; missing popularity scores below zero."""
    missing = replace(_match(), album_similarity=None, popularity=None)
    low = replace(_match("second"), album_similarity=0.99, popularity=100)
    assert preferred_match((low, missing), set()) == missing
    low = replace(low, album_similarity=None, popularity=0)
    assert preferred_match((missing, low), set()) == low


def test_no_eligible_match_and_equal_rank_preserve_selection() -> None:
    """Return none for empty/rejected observations and the first exact ranking tie."""
    assert preferred_match((), set()) is None
    assert preferred_match((replace(_match(), album_similarity=0.1),), set()) is None
    assert preferred_match((_match("first"), _match("second")), set()) == _match(
        "first"
    )
