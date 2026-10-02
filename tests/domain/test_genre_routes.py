"""Protect preserved genre order and original destination overlap semantics."""

import pytest

from spotify_manager.domain.genres import GenreRouteEntry
from spotify_manager.domain.genres import completed_slugs
from spotify_manager.domain.genres import destination_tracks
from spotify_manager.domain.genres import first_incomplete
from spotify_manager.domain.genres import genre_name
from spotify_manager.domain.genres import genre_slug


ROUTE = (GenreRouteEntry("First", "first", 1), GenreRouteEntry("Second", "second", 2))


@pytest.mark.parametrize(
    "completed,expected",
    [
        (set(), ROUTE[0]),
        ({"first"}, ROUTE[1]),
        ({"first", "second"}, None),
        ({"unrelated"}, ROUTE[0]),
    ],
)
def test_first_incomplete_preserves_route_authority(
    completed: set[str], expected: GenreRouteEntry | None
) -> None:
    """Use the original route order regardless of completed entries outside that route.

    Args:
        completed: Original saved identities.
        expected: First unfinished preserved entry.
    """
    assert first_incomplete(ROUTE, completed) == expected
    assert first_incomplete((), completed) is None


def test_genre_partition_preserves_duplicates_and_uri_spelling() -> None:
    """Compare trailing identity while retaining exact ordered source markers."""
    source = (
        "spotify:track:one",
        "spotify:track:two",
        "other:one",
        "spotify:track:two",
    )
    missing, present = destination_tracks(source, frozenset({"one", "unrelated"}))
    assert missing == (source[1], source[3])
    assert present == (source[0], source[2])
    assert destination_tracks((), frozenset()) == ((), ())


@pytest.mark.parametrize(
    "slug", ["", " padded", "padded ", "white space", "line\nbreak", "long" * 65]
)
def test_completed_genre_slug_boundaries(slug: str) -> None:
    """Reject each original invalid completed identity boundary.

    Args:
        slug: Invalid original completed identity.
    """
    with pytest.raises(ValueError, match="completed entries must be valid"):
        completed_slugs([slug])


def test_completed_genre_slugs_retain_order_and_the_original_length_limit() -> None:
    """Keep first occurrences and accept the exact original maximum length."""
    limit = "a" * 256
    assert completed_slugs(["second", "first", "second", limit]) == [
        "second",
        "first",
        limit,
    ]
    assert completed_slugs([]) == []


@pytest.mark.parametrize("slug", ["Upper", "with-hyphen", "with_underscore"])
def test_run_genre_slug_rejects_otherwise_valid_completed_identities(slug: str) -> None:
    """Run requests keep their original stricter lowercase alphanumeric rule.

    Args:
        slug: Valid completed identity, invalid run identity.
    """
    with pytest.raises(ValueError, match="only lowercase letters and digits"):
        genre_slug(slug)


def test_valid_genre_slug_and_display_name_are_not_rewritten() -> None:
    """Preserve validated identity and original display spelling."""
    assert genre_slug("genre123") == "genre123"
    assert genre_name("Genre Name") == "Genre Name"


@pytest.mark.parametrize("name", [" padded", "padded ", "\tname"])
def test_genre_display_name_keeps_original_padding_errors(name: str) -> None:
    """Reject original leading/trailing display whitespace.

    Args:
        name: Invalid padded display name.
    """
    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        genre_name(name)
