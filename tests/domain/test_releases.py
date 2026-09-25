"""Edition identity and deliberately different chronology policies."""

from datetime import date

import pytest

from spotify_manager.domain.releases import edition_details
from spotify_manager.domain.releases import edition_preference
from spotify_manager.domain.releases import is_non_studio_title
from spotify_manager.domain.releases import release_identity
from spotify_manager.domain.releases import review_date_key
from spotify_manager.domain.releases import studio_date_key


@pytest.mark.parametrize(
    "name,base,penalty,identity",
    [
        ("  ÁLBUM!  ", "ÁLBUM!", 0, "album"),
        ("Album (Deluxe Edition)", "Album", 1, "album"),
        ("Album - Remastered", "Album", 1, "album"),
        ("Album Deluxe", "Album", 1, "album"),
        ("Album (Deluxe) [Remastered]", "Album", 2, "album"),
        ("Album 25th Anniversary Edition", "Album", 1, "album"),
        ("Album (Studio)", "Album (Studio)", 0, "album studio"),
        ("(Deluxe)", "(Deluxe)", 1, "deluxe"),
        ("", "", 0, ""),
        ("Album — Deluxe — Live", "Album", 1, "album"),
    ],
)
def test_edition_identity(name: str, base: str, penalty: int, identity: str) -> None:
    """Preserve repeated suffix stripping, fallback names, and edition penalties.

    Args:
        name: Original title.
        base: Expected undecorated title.
        penalty: Number of removed suffixes.
        identity: Edition-neutral identity.
    """
    assert edition_details(name) == (base, penalty)
    assert release_identity(name) == identity


@pytest.mark.parametrize(
    "name,excluded",
    [
        ("Live at Home", True),
        ("Album (Live)", True),
        ("Ao Vivo", True),
        ("Greatest Hits", True),
        ("Original Soundtrack", True),
        ("Remixes", True),
        ("Lives in the Balance", False),
        ("Live Through This", False),
        ("Studio Album", False),
    ],
)
def test_studio_title_filter(name: str, excluded: bool) -> None:
    """Keep the conservative exclusion patterns from the studio catalog.

    Args:
        name: Release title.
        excluded: Whether the existing patterns classify it as non-studio.
    """
    assert is_non_studio_title(name) is excluded


@pytest.mark.parametrize(
    "value,studio,review",
    [
        ("2020", (0, date(2020, 1, 1).toordinal(), 0, "2020"), (2020, 12, 31, "2020")),
        (
            "2020-02",
            (0, date(2020, 2, 1).toordinal(), 0, "2020-02"),
            (2020, 2, 31, "2020-02"),
        ),
        (
            "2020-02-29",
            (0, date(2020, 2, 29).toordinal(), 0, "2020-02-29"),
            (2020, 2, 29, "2020-02-29"),
        ),
        ("2020-99-99", (1, 9999, 12, "2020-99-99"), (2020, 99, 99, "2020-99-99")),
        ("Unknown", (1, 9999, 12, "Unknown"), (9999, 12, 31, "Unknown")),
        ("", (1, 9999, 12, ""), (9999, 12, 31, "")),
        (
            "2020-01-01-7",
            (0, date(2020, 1, 1).toordinal(), 0, "2020-01-01-7"),
            (2020, 1, 1, "2020-01-01-7"),
        ),
    ],
)
def test_chronology_policies_remain_distinct(
    value: str,
    studio: tuple[int, int, int, str],
    review: tuple[int, int, int, str],
) -> None:
    """Keep start-of-period validation separate from tolerant end-of-period sorting.

    Args:
        value: Full, partial, invalid, or extended Spotify date.
        studio: Expected studio-discography key.
        review: Expected artist-review key.
    """
    assert studio_date_key(value) == studio
    assert review_date_key(value) == review


def test_saved_edition_beats_plain_unsaved_edition() -> None:
    """Keep a saved deluxe edition ahead of an unsaved original."""
    saved = edition_preference(True, False, 2, 30, "2025", "Album Deluxe", "z")
    plain = edition_preference(False, True, 0, 10, "2000", "Album", "a")
    assert saved < plain


def test_edition_tie_breakers_are_stable() -> None:
    """Apply decoration, track count, date, name, and identifier tie breakers."""
    first = edition_preference(True, True, 0, 10, "2020", "Alpha", "a")
    competitors = (
        edition_preference(True, False, 0, 10, "2020", "Alpha", "a"),
        edition_preference(True, True, 1, 10, "2020", "Alpha", "a"),
        edition_preference(True, True, 0, 11, "2020", "Alpha", "a"),
        edition_preference(True, True, 0, 10, "2021", "Alpha", "a"),
        edition_preference(True, True, 0, 10, "2020", "Beta", "a"),
        edition_preference(True, True, 0, 10, "2020", "Alpha", "b"),
    )
    assert all(first < candidate for candidate in competitors)
