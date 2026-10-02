"""Verify original annual calendar ranks, exact qualification and marker ordering."""

import json
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.domain.annual_history import rank_year
from spotify_manager.domain.annual_selection import existing_primary_marker
from spotify_manager.domain.annual_selection import marker_position
from spotify_manager.domain.annual_selection import matching_playlist_ids
from spotify_manager.domain.annual_selection import pending_uris
from spotify_manager.domain.annual_selection import selected_track
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch


def _cases() -> list[dict[str, object]]:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures/refactor/new_year_rankings.json"
    )
    return cast(list[dict[str, object]], json.loads(path.read_text()))


def _history(raw: object) -> tuple[Scrobble, ...]:
    plays = []
    for row in cast(list[dict[str, object]], raw):
        plays.append(
            Scrobble(
                cast(str, row["track"]),
                cast(str, row["artist"]),
                cast(str, row["album"]),
                cast(int, row["timestamp_ms"]),
            )
        )
    return tuple(plays)


@pytest.mark.parametrize("case", _cases())
def test_annual_ranks_match_original_calendar_and_display_labels(
    case: dict[str, object],
) -> None:
    """Retain calendar edges, raw display labels, blank parts and deterministic ties.

    Args:
        case: Original immutable dated history and rankings.
    """
    assert (
        rank_year(
            _history(case["history"]),
            cast(int, case["year"]),
            ZoneInfo("Europe/Berlin"),
        )
        == case["outcome"]
    )


def _match(uri: str, similarity: float) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        uri, uri, "Title", ("Artist",), "Album", 1, similarity, None, None
    )


def _marker(uri: str, artist: str) -> PlaylistTrack:
    release = ReleaseCandidate(
        "album", "album", "Album", "Album", "2020", 10, artist, artist
    )
    return PlaylistTrack(uri, uri, "Title", artist, artist, release)


def test_annual_marker_selection_prefers_first_exact_then_first_qualified() -> None:
    """Retain exact-match priority without adding popularity or saved-status ranking."""
    approximate, exact, later = (
        _match("approximate", 0.8),
        _match("exact", 1.0),
        _match("later", 1.0),
    )
    assert selected_track((approximate, exact, later)) == exact
    assert selected_track((approximate,)) == approximate
    assert selected_track(()) is None


def test_annual_current_markers_preserve_primary_credit_and_first_occurrence() -> None:
    """Retain primary-credit reuse, absent markers and first reorder positions."""
    tracks = (
        _marker("other", "other"),
        _marker("first", "artist"),
        _marker("second", "artist"),
        _marker("first", "artist"),
    )
    assert existing_primary_marker(tracks, "artist") == "first"
    assert existing_primary_marker(tracks, "absent") is None
    assert pending_uris(["first", "missing", "other", "last"], tracks) == [
        "missing",
        "last",
    ]
    assert marker_position(tracks, "first") == 1
    with pytest.raises(StopIteration):
        marker_position(tracks, "missing")


def test_annual_owned_names_use_casefold_without_trimming_or_extra_identity() -> None:
    """Retain duplicate-row collapse and original casefold-only title matching."""
    playlists = (
        OwnedPlaylist("a", "Chart", 0),
        OwnedPlaylist("a", "CHART", 0),
        OwnedPlaylist("b", " Chart ", 0),
        OwnedPlaylist("c", "Other", 0),
    )
    assert matching_playlist_ids(playlists, "chart") == {"a"}
    assert matching_playlist_ids(playlists, " Chart ") == {"b"}
    assert matching_playlist_ids(playlists, "missing") == set()
