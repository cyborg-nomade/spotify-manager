"""Independent recommendation ranking, exclusions and ordered addition rules."""

from dataclasses import replace

import pytest

from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_matching import RecommendationSelection
from spotify_manager.domain.recommendation_matching import (
    preferred_recommendation_match,
)


EMPTY = PlaylistState(0, frozenset())


def _candidate(artist: str = "artist", title: str = "song") -> FoundArtCandidate:
    return FoundArtCandidate(artist, title, (artist, title), 1, 1, ())


def _match(
    identity: str = "track",
    *,
    popularity: int | None = 50,
    track_similarity: float = 1.0,
    album_similarity: float | None = None,
    liked: bool = False,
    search_rank: int = 1,
) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        identity,
        identity,
        "Song",
        ("Artist",),
        "Album",
        search_rank,
        track_similarity,
        album_similarity,
        popularity,
        liked,
    )


@pytest.mark.parametrize("liked", [False, True])
def test_preference_uses_live_status_similarity_popularity_and_original_order(
    liked: bool,
) -> None:
    """Retain album-independent ranking and replace stored liked flags.

    Args:
        liked: Requested live-status group.
    """
    best = _match("best", popularity=90, album_similarity=0.0, liked=not liked)
    matches = (
        _match("similarity", track_similarity=0.9, popularity=100),
        _match("missing", popularity=None),
        _match("lower", popularity=80, album_similarity=1.0),
        _match("later", popularity=90, search_rank=2),
        best,
    )
    ids = {match.spotify_id for match in matches} if liked else set()
    assert preferred_recommendation_match(matches, ids, liked=liked) == replace(
        best, liked=liked
    )
    assert preferred_recommendation_match(matches, ids, liked=not liked) is None
    assert preferred_recommendation_match((), ids, liked=liked) is None


def test_equal_rank_retains_first_search_observation() -> None:
    """Preserve the first encounter when all preference components tie."""
    first, second = _match("first"), _match("second")
    assert preferred_recommendation_match((first, second), set(), liked=False) == first


def test_artist_exclusion_precedes_key_membership_and_ignores_matches() -> None:
    """An earlier accepted artist overrides even exact destination-key membership."""
    item = _candidate()
    selection = RecommendationSelection(
        PlaylistState(1, frozenset(), frozenset({item.key})), 2, False
    )
    selection.selected_artists.add("artist")
    assert selection.skips_search(item)
    assert selection.observe(item, (_match(),), {"track"})
    assert selection.results[0].action == "artist already selected"
    assert selection.results[0].match is None
    assert selection.pending == []


def test_key_exclusion_precedes_live_liked_matches() -> None:
    """Exact candidate keys are reported present with no preferred match."""
    item = _candidate()
    selection = RecommendationSelection(
        PlaylistState(1, frozenset(), frozenset({item.key})), 2, False
    )
    assert selection.skips_search(item)
    assert selection.observe(item, (_match(),), {"track"})
    assert selection.results[0].action == "already present"
    assert selection.results[0].match is None


def test_liked_preference_suppresses_unliked_and_existing_ids() -> None:
    """Any live liked match suppresses additions before destination ID checks."""
    selection = RecommendationSelection(
        PlaylistState(1, frozenset({"liked"})), 1, False
    )
    liked = _match("liked", track_similarity=0.8)
    assert not selection.skips_search(_candidate())
    assert selection.observe(_candidate(), (_match("unliked"), liked), {"liked"})
    assert selection.results[0].match == replace(liked, liked=True)
    assert selection.results[0].action == "liked"
    assert selection.pending == []


@pytest.mark.parametrize("dry_run,action", [(False, "added"), (True, "would add")])
def test_unique_addition_and_all_post_capacity_outcomes(
    dry_run: bool, action: str
) -> None:
    """Continue skipped outcomes after capacity and stop at the next eligible addition.

    Args:
        dry_run: Original presentation mode.
        action: Expected addition action.
    """
    selection = RecommendationSelection(
        PlaylistState(1, frozenset({"present"})), 1, dry_run
    )
    assert selection.observe(_candidate(), (_match(),), set())
    assert selection.skips_search(_candidate("artist", "other"))
    assert selection.observe(_candidate("new", "missing"), (), set())
    assert selection.observe(_candidate("new", "present"), (_match("present"),), set())
    assert selection.observe(_candidate("new", "duplicate"), (_match(),), set())
    assert not selection.observe(_candidate("new", "stop"), (_match("new"),), set())
    assert [result.action for result in selection.results] == [
        action,
        "no Spotify match",
        "already present",
        "duplicate",
    ]
    assert selection.pending == [_match()]
    assert selection.pending_ids == {"track"}
    assert selection.selected_artists == {"artist"}


def test_stored_liked_status_does_not_suppress_unliked_observation() -> None:
    """Live status resets stale liked metadata before accepting an addition."""
    selection = RecommendationSelection(EMPTY, 1, False)
    assert selection.observe(_candidate(), (_match(liked=True),), set())
    assert selection.pending == [_match(liked=False)]
