"""Verify playlist order, duplicate counts, and conservative match evidence."""

from typing import Literal

from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_library_values import MirrorSource
from spotify_manager.domain.listening_playlist import PlaylistOptions
from spotify_manager.domain.listening_playlist import PlaylistReview
from spotify_manager.domain.listening_playlist import PlaylistSummary
from spotify_manager.domain.listening_playlist import RecordedTrack
from spotify_manager.domain.listening_playlist import build_playlist_preview
from spotify_manager.domain.listening_playlist import page_playlist


def track(key: str, suffix: str) -> LibraryEntry:
    """Create one published liked-track fixture."""
    return LibraryEntry("track", key, key, "Artist", "spotify:track:" + suffix * 22)


def catalog(
    state: Literal["ready", "missing"] = "ready",
) -> LibraryCatalog:
    """Provide one verified track collection with exact and ambiguous names."""
    source = MirrorSource("track", state, None, None, None, 4, "")
    entries = (
        track("later", "a"),
        track("early", "b"),
        track("ambiguous", "c"),
        track("ambiguous", "d"),
    )
    return LibraryCatalog("l1-fixture", "revision", (source,), entries)


def test_playlist_preserves_first_appearance_and_counts_track_uri_repeats() -> None:
    """Keep the first Spotify appearance when a reviewed alias shares that URI."""
    history = (
        RecordedTrack("early", "Early", "Artist", 3, 10),
        RecordedTrack("later", "Later", "Artist", 1, 20),
        RecordedTrack("alias", "Alias", "Artist", 2, 20),
        RecordedTrack("ambiguous", "Multiple editions", "Artist", 4, 30),
        RecordedTrack("unknown", "Unknown", "Artist", 1, 40),
        RecordedTrack("expired", "Expired review", "Artist", 1, 50),
    )
    reviews = (
        PlaylistReview("alias", track("early", "b").uri),
        PlaylistReview("expired", track("", "z").uri),
    )
    result = build_playlist_preview(history, catalog(), reviews)
    assert result.summary == PlaylistSummary(12, 2, 4, 3, 6)
    assert [row.track.key for row in result.tracks] == ["early", "later"]
    assert [row.position for row in result.tracks] == [1, 2]
    assert result.tracks[0].plays == 5
    assert [row.reason for row in result.unresolved] == [
        "ambiguous",
        "unmatched",
        "review_unavailable",
    ]
    assert (
        page_playlist(result, PlaylistOptions("duplicates", 1, 1)).items
        == result.tracks[:1]
    )
    page = page_playlist(result, PlaylistOptions("unresolved", 2, 1))
    assert page.total == 3 and page.items == result.unresolved[1:2]


def test_review_selects_one_candidate_and_missing_source_never_resolves() -> None:
    """Recheck the chosen URI in the pinned publication and report lost coverage."""
    history = (RecordedTrack("ambiguous", "Name", "Artist", 2, 10),)
    choice = PlaylistReview("ambiguous", track("ambiguous", "d").uri)
    reviewed = build_playlist_preview(history, catalog(), (choice,))
    assert reviewed.tracks[0].evidence == "reviewed"
    assert reviewed.tracks[0].track.uri == choice.uri
    missing = build_playlist_preview(history, catalog("missing"), (choice,))
    assert missing.summary == PlaylistSummary(2, 0, 0, 1, 2)
    assert missing.unresolved[0].reason == "publication_unavailable"
