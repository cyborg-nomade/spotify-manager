"""Protect the original historical candidate and membership observation rules."""

import pytest

from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import candidate_ids
from spotify_manager.domain.history_matching import candidate_similarity
from spotify_manager.domain.history_matching import liked_identities


@pytest.mark.parametrize(
    "artist,title,artists,threshold,expected",
    [
        ("", "Track", ("Artist",), 0.9, None),
        ("Artist", "Track", (), 0.9, None),
        ("Artist", "Track", ("Other",), 0.9, None),
        ("Artist", "Track", ("Other", "Artist"), 0.9, 1.0),
        ("Artist", "Different", ("Artist",), 0.9, None),
        ("Artist", "Track", ("Artist",), 1.0, 1.0),
        ("Artist", "Track", ("Artist",), float("nan"), 1.0),
    ],
)
def test_original_artist_and_title_qualification(
    artist: str,
    title: str,
    artists: tuple[str, ...],
    threshold: float,
    expected: float | None,
) -> None:
    """Retain artist normalization before title comparison and inclusive thresholds.

    Args:
        artist: Original expected artist.
        title: Original observed title.
        artists: Original ordered observed credits.
        threshold: Original overridable title threshold.
        expected: Original qualified similarity or no candidate.
    """
    assert candidate_similarity(artist, "Track", artists, title, threshold) == expected


def observed_track(identifier: str) -> SpotifyTrackMatch:
    """Supply a complete original search candidate.

    Args:
        identifier: Original track identity.

    Returns:
        Original minimal qualified metadata.
    """
    return SpotifyTrackMatch(
        identifier, "uri", "Track", ("Artist",), "Album", 1, 1.0, 1.0, 50
    )


def test_candidate_ids_retain_first_identity_encounter() -> None:
    """Deduplicate across selections without moving repeated identities."""
    one, two = observed_track("one"), observed_track("two")
    assert candidate_ids([(one, two), (), (one,)]) == ["one", "two"]
    assert candidate_ids([]) == []


def test_raw_membership_keeps_original_truthiness_and_duplicates() -> None:
    """Keep any truthy original observation for a repeated track identity."""
    assert liked_identities(["one", "two", "one"], [True, "", False]) == {"one"}
    assert liked_identities(["one"], ["truthy"]) == {"one"}
    assert liked_identities([], []) == set()
    with pytest.raises(ValueError):
        liked_identities(["one"], [])
