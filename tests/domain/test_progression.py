"""Track-order, credit, and missing-observation contracts."""

from dataclasses import dataclass

import pytest

from spotify_manager.domain.progression import advance_streak
from spotify_manager.domain.progression import next_liked_track
from spotify_manager.domain.progression import primary_artist_tracks
from spotify_manager.domain.progression import trailing_unliked


@dataclass(frozen=True)
class Track:
    """Only the domain facts needed by the progression rules.

    Args:
        spotify_id: Track identity in observed liked statuses.
        primary_artist_id: First artist accepted by the boundary codec.
    """

    spotify_id: str
    primary_artist_id: str = "primary"


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ((), 0),
        ((True,), 0),
        ((False,), 1),
        ((False, False, False), 3),
        ((False, True, False), 1),
        ((True, False, False), 0),
    ],
)
def test_trailing_streak(statuses: tuple[bool, ...], expected: int) -> None:
    """Stop counting at the nearest liked predecessor.

    Args:
        statuses: Reverse-ordered preceding observations.
        expected: Unliked tail length.
    """
    assert trailing_unliked(iter(statuses)) == expected


@pytest.mark.parametrize(
    "prior,current,expected",
    [
        (0, False, 1),
        (2, False, 3),
        (3, False, 4),
        (3, True, 0),
        (-2, False, -1),
        (-2, True, 0),
    ],
)
def test_streak_transition(prior: int, current: bool, expected: int) -> None:
    """Retain persisted streak values and reset on the current like.

    Args:
        prior: Stored streak.
        current: Current liked status.
        expected: Streak after consuming the current track.
    """
    assert advance_streak(prior, current) == expected


def test_streak_stops_consuming_after_first_like() -> None:
    """Avoid consulting observations beyond the nearest preceding liked track."""
    statuses = iter((False, True, False))
    assert trailing_unliked(statuses) == 1
    assert next(statuses) is False


def test_primary_credit_filter_preserves_identity_order_and_duplicates() -> None:
    """Exclude featured credits without sorting or deduplicating eligible tracks."""
    first = Track("a")
    featured = Track("b", "another")
    last = Track("c")
    result = primary_artist_tracks((first, featured, last, first), "primary")
    assert result == (first, last, first)
    assert result[0] is first
    assert primary_artist_tracks((), "primary") == ()


@pytest.mark.parametrize(
    "index,expected",
    [(None, None), (0, "b"), (1, "c"), (2, None), (9, None), (-1, "b")],
)
def test_next_liked_successor(index: int | None, expected: str | None) -> None:
    """Find the first liked successor and preserve unknown/end-of-release behavior.

    Args:
        index: Current marker position.
        expected: First eligible successor identity, if any.
    """
    tracks = (Track("a"), Track("b"), Track("c"))
    result = next_liked_track(tracks, index, {"a": False, "b": True, "c": True})
    assert (result.spotify_id if result else None) == expected
    if result is not None:
        assert any(result is track for track in tracks)


def test_missing_liked_observations_remain_errors_only_when_consulted() -> None:
    """Stop before later missing statuses, but reject a missing immediate status."""
    tracks = (Track("a"), Track("b"), Track("c"))
    assert next_liked_track(tracks, 0, {"b": True}) is tracks[1]
    assert next_liked_track(tracks, None, {}) is None
    assert next_liked_track((), 0, {}) is None
    assert next_liked_track(tracks, 0, {"b": False, "c": False}) is None
    with pytest.raises(KeyError, match="b"):
        next_liked_track(tracks, 0, {})
