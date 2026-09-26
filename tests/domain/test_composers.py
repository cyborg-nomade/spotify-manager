"""Conservative composer routing runs without SDKs or application startup."""

import pytest

from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.composers import composer_playlist_candidates
from spotify_manager.domain.composers import is_composer_playlist_candidate
from spotify_manager.domain.composers import name_tokens


@pytest.mark.parametrize(
    ("artist", "title", "matches"),
    [
        ("", "[CD] Complete works", False),
        ("Bach", "[CD] Complete Bach works", True),
        ("Johann Sebastian Bach", "[CD] Bach works vol 1", True),
        ("Johann Sebastian Bach", "[CD] J S Bach works", False),
        ("Johann Sebastian Bach", "[CD] Handel works", False),
        ("Johann Sebastian Bach", "[CD] Johann Sebastian Bach favorites", True),
        ("A Very Long Artist Name", "[CD] Short", False),
        ("Roger Taylor", "[CD] Samuel Coleridge-Taylor works", False),
        ("Samuel Coleridge-Taylor", "[CD] Complete Samuel Coleridge-Taylor", True),
        ("The Smiths", "[CD] Smiths works", False),
        ("Smith Quartet", "[CD] Quartet works", False),
        ("A3 Smith", "[CD] Smith works", False),
        ("John Smith Jr II", "[CD] Smith works", True),
        ("Jr II", "[CD] Jr works", True),
        ("A Band", "[CD] A Band works", True),
        ("Bach", "[CD] Bachman works", False),
        ("Bach", "Bach works", False),
        ("Bach", "[cd] Bach works", False),
        ("Béla Bartók", "[CD] Bartok works", True),
    ],
)
def test_composer_match_table(artist: str, title: str, matches: bool) -> None:
    """Keep exact sequences and conservative personal surnames distinct.

    Args:
        artist: Spotify artist name.
        title: Observed playlist title.
        matches: Frozen eligibility outcome.
    """
    playlist = OwnedPlaylist("route", title, 3)
    candidates = composer_playlist_candidates(
        artist, (playlist,), excluded_playlist_ids=frozenset()
    )
    assert candidates == ((playlist,) if matches else ())
    assert (
        is_composer_playlist_candidate(
            artist, "route", (playlist,), excluded_playlist_ids=frozenset()
        )
        == matches
    )


def test_exclusions_preserve_order_and_duplicates() -> None:
    """Explicit route exclusions cannot alter the order of other observations."""
    queue = OwnedPlaylist("queue", "[CD] Bach", 1)
    first = OwnedPlaylist("first", "[CD] Bach", 1)
    second = OwnedPlaylist("second", "[CD] Bach", 1)
    candidates = composer_playlist_candidates(
        "Bach",
        (first, queue, second, first),
        excluded_playlist_ids=frozenset({"queue"}),
    )
    assert candidates == (first, second, first)
    assert not is_composer_playlist_candidate(
        "Bach", "missing", (first,), excluded_playlist_ids=frozenset()
    )


def test_name_normalization_transliterates_punctuation_and_numbers() -> None:
    """Whole-token matching retains digits and transliterates accented letters."""
    assert name_tokens("BÉLA — Bartók's No. 3") == ("bela", "bartok", "s", "no", "3")
