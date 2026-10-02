"""Protect ignored historical metadata, native paging and timestamp boundaries."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from functools import partial
from pathlib import Path

import pytest

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure import history_export
from spotify_manager.infrastructure import history_playlist
from spotify_manager.infrastructure.history_matching_records import artist_names
from spotify_manager.infrastructure.history_matching_records import matching_track
from spotify_manager.infrastructure.lookup_records import track_identities
from tests.support.library_lookup_run import raw_track


@dataclass
class PlaylistPages:
    """Supply original raw pages and record every raw offset.

    Args:
        pages: Original ordered raw page responses.
        offsets: Original observed request offsets.
    """

    pages: list[object]
    offsets: list[int] = field(default_factory=list)

    def read(self, offset: int) -> object:
        """Read the next original page without normalizing raw row counts.

        Args:
            offset: Original raw-row offset.

        Returns:
            Original unvalidated page response.
        """
        self.offsets.append(offset)
        return self.pages.pop(0)


@pytest.mark.parametrize("page", [None, {}, {"items": None}])
def test_playlist_page_shape_is_unchanged(page: object) -> None:
    """Retain original invalid-page diagnostics.

    Args:
        page: Original malformed response.
    """
    with pytest.raises(SpotifyTrackResolutionError, match="invalid playlist"):
        history_playlist.state(PlaylistPages([page]).read, artist_names, "target")


def test_playlist_ignores_missing_rows_and_keeps_raw_total_offsets() -> None:
    """Preserve total fallback, unchecked continuation values and empty identities."""
    rows: list[object] = [
        None,
        {},
        {"track": {}},
        {"track": {"id": "id"}},
        {"track": {"name": "!!!", "artists": [{"name": "!!!"}]}},
        {"track": {"name": "Title", "artists": []}},
    ]
    pages = PlaylistPages(
        [
            {"items": rows, "total": 7},
            {"items": [{"track": raw_track("last")}], "total": 7},
        ]
    )
    result = history_playlist.state(pages.read, artist_names, "target")
    assert pages.offsets == [0, 6] and result.total_items == 7
    assert result.track_ids == frozenset({"id", "last"})
    assert result.primary_artist_keys == frozenset({"artist"})


def test_playlist_non_string_continuation_and_empty_next_guard() -> None:
    """Follow truthy original continuations and reject empty active pages."""
    pages = PlaylistPages([{"items": [{}], "next": True}, {"items": [], "next": None}])
    assert history_playlist.state(pages.read, artist_names, "target").total_items == 1
    assert pages.offsets == [0, 1]
    with pytest.raises(SpotifyTrackResolutionError, match="empty playlist"):
        history_playlist.state(
            PlaylistPages([{"items": [], "next": True}]).read, artist_names, "target"
        )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"id": "id", "name": "Track", "uri": "uri", "artists": None},
        {"id": "id", "name": "Track", "uri": "uri", "artists": [None, {}]},
    ],
)
def test_historical_match_requires_original_minimum_metadata(raw: object) -> None:
    """Skip incomplete raw search candidates without tightening optional fields.

    Args:
        raw: Original raw candidate response.
    """
    assert (
        matching_track(Scrobble("Track", "Artist", "Album", 1000), raw, 1, 0.9) is None
    )


def test_match_keeps_guest_artist_names_and_unknown_optional_metadata() -> None:
    """Keep raw artist order and tolerant popularity/album parsing."""
    raw = raw_track("track")
    raw["artists"] = [None, {"name": "Other"}, {}, {"name": "Artist"}]
    raw["popularity"] = "popular"
    raw["album"] = None
    result = matching_track(Scrobble("Track", "Artist", "", 1000), raw, 2, 0.9)
    assert result is not None and result.artists == ("Other", "Artist")
    assert result.popularity is None and result.album == "" and result.search_rank == 2
    assert artist_names({"artists": "Artist"}) == ()
    assert track_identities([None, raw_track("valid")])[0].spotify_id == "valid"


def payload(rows: list[object], path: Path) -> dict[str, object]:
    """Supply original raw history without touching a production file.

    Args:
        rows: Original unchecked history records.
        path: Original source path.

    Returns:
        Original export container.
    """
    return {"scrobbles": rows}


@pytest.mark.parametrize("timestamp", [10**30, -(10**30)])
def test_history_grouping_retains_original_final_time_errors(timestamp: int) -> None:
    """Translate only original out-of-range datetime observations.

    Args:
        timestamp: Original matching-row milliseconds.
    """
    rows: list[object] = [{"date": timestamp}]
    with pytest.raises(
        LastFmExportError, match="Scrobble 0 has an out-of-range timestamp"
    ) as raised:
        history_export.by_date(partial(payload, rows), Path("history.json"), UTC)
    assert isinstance(raised.value.__cause__, (OSError, OverflowError, ValueError))
