"""Current-year completion normalizes editions while retaining distinct title rules."""

from dataclasses import replace
from datetime import date

import pytest

from spotify_manager.domain.discovery_history import annual_release_key
from spotify_manager.domain.discovery_history import annual_scrobble_index
from spotify_manager.domain.discovery_history import release_was_played
from spotify_manager.domain.discovery_history import review_catalog
from spotify_manager.domain.discovery_history import scrobble_track_identity
from spotify_manager.domain.discovery_history import scrobbled_titles
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.titles import without_sliding_qualifiers
from tests.support.discovery_values import release
from tests.support.discovery_values import track


@pytest.mark.parametrize(
    "title,expected",
    [
        (" Song (Remastered) - Live [Mono] ", "Song"),
        ("Song — Acoustic", "Song"),
        ("Song – Radio Edit", "Song"),
        ("Song (Part Two)", "Song (Part Two)"),
        ("Song - Part Two", "Song - Part Two"),
        ("", ""),
        (" Song ", "Song"),
    ],
)
def test_sliding_qualifiers_preserve_unrecognized_suffixes(
    title: str, expected: str
) -> None:
    """Repeated removal stops when neither suffix matches the existing patterns.

    Args:
        title: Original potentially decorated title.
        expected: Existing normalized display title.
    """
    assert without_sliding_qualifiers(title) == expected


def test_artist_release_and_track_codecs_keep_their_distinct_word_boundaries() -> None:
    """Artist identities collapse words; track/release identities retain spaces."""
    assert annual_release_key("Ártist Name", "The Album (Deluxe)") == (
        "artistname",
        "the album",
    )
    assert scrobble_track_identity("The Song - Live (Remastered)") == "the song"


def test_annual_index_filters_year_and_empty_identities_then_deduplicates_titles() -> (
    None
):
    """The caller's local dates select the year; duplicate editions count once."""
    current = [
        Scrobble("Song", "Artist", "Album", 0),
        Scrobble("Song - Live", "Artist", "Album (Deluxe)", 0),
    ]
    invalid = [
        Scrobble("Song", "", "Album", 0),
        Scrobble("Song", "Artist", "", 0),
        Scrobble("", "Artist", "Album", 0),
    ]
    history = {
        date(2026, 1, 1): current + invalid,
        date(2025, 12, 31): [Scrobble("Old", "Artist", "Album", 0)],
    }
    assert annual_scrobble_index(history, 2026) == {
        ("artist", "album"): frozenset({"song"})
    }
    assert annual_scrobble_index({}, 2026) == {}


def test_review_catalog_retains_fallback_until_studio_count_is_sufficient() -> None:
    """The preference threshold counts entries rather than deduplicated release IDs."""
    album, single = release("album"), replace(release("single"), tier=1)
    assert review_catalog((album, single)) == (album, single)
    assert review_catalog((single, album, album, album, album)) == (album,) * 4
    assert review_catalog((single, album), release_limit=1) == (album,)


def test_title_prefilter_unions_artists_only_for_the_matching_release() -> None:
    """Artist-specific matching is intentionally deferred until tracks are observed."""
    index = {
        ("artist", "album"): frozenset({"one", "two"}),
        ("guest", "album"): frozenset({"two", "three"}),
        ("artist", "other"): frozenset({"excluded"}),
    }
    assert scrobbled_titles(index, "album") == {"one", "two", "three"}
    assert scrobbled_titles(index, "missing") == set()


def test_completion_requires_each_liked_title_under_its_actual_primary_credit() -> None:
    """Guest credits participate in completion instead of being filtered out."""
    tracks = (
        track("one"),
        track("two"),
        track("three"),
        replace(track("guest"), primary_artist_name="Guest"),
    )
    index = {("artist", "album"): frozenset({"one", "two", "three", "guest"})}
    assert release_was_played(release("album"), tracks, {}, index)
    assert not release_was_played(release("album"), tracks, {"guest": True}, index)
    index[("guest", "album")] = frozenset({"guest"})
    assert release_was_played(release("album"), tracks, {"guest": True}, index)


def test_normalized_duplicate_tracks_count_once_and_fallback_needs_one_title() -> None:
    """Track IDs and edition duplicates do not inflate the distinct-title threshold."""
    tracks = (track("song"), replace(track("edition"), name="Song - Live"))
    index = {("artist", "album"): frozenset({"song"})}
    assert not release_was_played(release("album"), tracks, {}, index)
    assert release_was_played(replace(release("album"), tier=1), tracks, {}, index)
    assert release_was_played(release("album"), tracks, {}, index, studio_minimum=1)
