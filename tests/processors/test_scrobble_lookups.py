"""Tests for the live Spotify track to Last.fm history lookup."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.processors import scrobble_lookups
from spotify_manager.routines import blast_from_past


BERLIN = ZoneInfo("Europe/Berlin")


def _spotify_track(
    *,
    spotify_id: str = "track-id",
    name: str = "The Song - 2011 Remaster",
    artist: str = "The Artist",
    album: str = "The Album",
    popularity: int = 50,
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "popularity": popularity,
    }


def _history(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"scrobbles": records}), encoding="utf-8")


def _timestamp(value: datetime) -> int:
    return round(value.timestamp() * 1000)


def test_track_status_returns_latest_matching_scrobble_and_current_season(
    tmp_path: Path,
) -> None:
    history = tmp_path / "history.json"
    older = datetime(2026, 6, 4, 9, 30, tzinfo=BERLIN)
    latest = datetime(2026, 8, 20, 21, 15, tzinfo=BERLIN)
    _history(
        history,
        [
            {"artist": "The Artist", "track": "The Song", "date": _timestamp(older)},
            {"artist": "Other", "track": "The Song", "date": _timestamp(latest)},
            {"artist": "The Artist", "track": "The Song", "date": _timestamp(latest)},
        ],
    )
    spotify = SimpleNamespace(track=lambda _track_id: _spotify_track())

    result = scrobble_lookups.get_track_scrobble_status(
        spotify,
        track_id="track-id",
        path=history,
        now=datetime(2026, 8, 29, 12, tzinfo=BERLIN),
    )

    assert result.last_scrobbled_at == latest
    assert result.last_scrobble_season == "Summer 2026"
    assert result.current_season == "Summer 2026"
    assert result.in_current_season is True


def test_track_status_reports_never_scrobbled(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    _history(history, [])
    spotify = SimpleNamespace(track=lambda _track_id: _spotify_track())

    result = scrobble_lookups.get_track_scrobble_status(
        spotify,
        track_id="track-id",
        path=history,
        now=datetime(2026, 8, 29, 12, tzinfo=BERLIN),
    )

    assert result.last_scrobbled_at is None
    assert result.last_scrobble_season is None
    assert result.in_current_season is False


@pytest.mark.parametrize(
    ("when", "label"),
    [
        (datetime(2026, 2, 28, tzinfo=BERLIN), "Winter 2025/2026"),
        (datetime(2026, 3, 1, tzinfo=BERLIN), "Spring 2026"),
        (datetime(2026, 6, 1, tzinfo=BERLIN), "Summer 2026"),
        (datetime(2026, 9, 1, tzinfo=BERLIN), "Autumn 2026"),
        (datetime(2026, 12, 1, tzinfo=BERLIN), "Winter 2026/2027"),
    ],
)
def test_season_window_uses_berlin_meteorological_boundaries(
    when: datetime,
    label: str,
) -> None:
    assert scrobble_lookups.season_window(when).label == label


def test_resolve_live_track_prefers_most_popular_duplicate_for_same_artist() -> None:
    spotify = SimpleNamespace(
        search=lambda **_kwargs: {
            "tracks": {
                "items": [
                    _spotify_track(spotify_id="quiet", popularity=20),
                    _spotify_track(spotify_id="popular", popularity=80),
                ]
            }
        }
    )

    result = scrobble_lookups.resolve_live_track(
        spotify,
        name="The Song - 2011 Remaster",
    )

    assert result.spotify_id == "popular"


def test_resolve_live_track_reports_different_artists_as_ambiguous() -> None:
    spotify = SimpleNamespace(
        search=lambda **_kwargs: {
            "tracks": {
                "items": [
                    _spotify_track(spotify_id="one", artist="Artist One"),
                    _spotify_track(spotify_id="two", artist="Artist Two"),
                ]
            }
        }
    )

    with pytest.raises(scrobble_lookups.AmbiguousTrackError) as error:
        scrobble_lookups.resolve_live_track(
            spotify,
            name="The Song - 2011 Remaster",
        )

    assert [candidate["artist"] for candidate in error.value.candidates] == [
        "Artist One",
        "Artist Two",
    ]


def test_track_status_rejects_invalid_matching_timestamp(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    _history(
        history,
        [{"artist": "The Artist", "track": "The Song", "date": "invalid"}],
    )
    spotify = SimpleNamespace(track=lambda _track_id: _spotify_track())

    with pytest.raises(blast_from_past.LastFmExportError, match="timestamp"):
        scrobble_lookups.get_track_scrobble_status(
            spotify,
            track_id="track-id",
            path=history,
        )


def test_resolve_live_track_validates_search_response() -> None:
    with pytest.raises(scrobble_lookups.SpotifyLookupResponseError):
        scrobble_lookups.resolve_live_track(
            SimpleNamespace(search=lambda **_kwargs: {}),
            name="The Song",
        )


def test_resolve_live_track_requires_lookup_argument() -> None:
    with pytest.raises(ValueError, match="provide name"):
        scrobble_lookups.resolve_live_track(object())  # type: ignore[arg-type]
