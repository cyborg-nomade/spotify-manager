"""Tests for the Daily Mind Radio anniversary routine."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio


def spotify_track(
    spotify_id: str,
    track: str,
    artist: str,
    album: str,
    popularity: int = 50,
) -> dict[str, object]:
    """Return one Spotify-shaped search result."""
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": track,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "popularity": popularity,
    }


class FakeSpotify:
    """Small Spotify stand-in for search, library, and playlist operations."""

    def __init__(self) -> None:
        self.playlist_tracks: list[dict[str, object]] = []
        self.search_results: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.posts: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, limit: int, offset: int) -> dict[str, object]:
        assert path == "playlists/daily/items"
        items = [
            {"item": track} for track in self.playlist_tracks[offset : offset + limit]
        ]
        return {
            "items": items,
            "total": len(self.playlist_tracks),
            "next": (
                "next" if offset + len(items) < len(self.playlist_tracks) else None
            ),
        }

    def search(
        self,
        q: str,
        limit: int,
        offset: int,
        **kwargs: str,
    ) -> dict[str, object]:
        assert kwargs["type"] == "track"
        assert limit == blast_from_past.SPOTIFY_SEARCH_LIMIT
        assert offset == 0
        return {"tracks": {"items": self.search_results.get(q, [])}}

    def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        return [spotify_id in self.liked_ids for spotify_id in ids]

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, str]:
        self.posts.append((path, payload))
        return {"snapshot_id": "snapshot"}


def export_scrobble(
    played_on: date,
    track: str,
    album: str = "Album",
) -> dict[str, object]:
    """Return one Last.fm-export scrobble at noon UTC."""
    played_at = datetime(
        played_on.year,
        played_on.month,
        played_on.day,
        12,
        tzinfo=UTC,
    )
    return {
        "track": track,
        "artist": "Artist",
        "album": album,
        "date": int(played_at.timestamp() * 1000),
    }


def write_export(path: Path, scrobbles: list[dict[str, object]]) -> None:
    """Write a minimal Last.fm export."""
    path.write_text(json.dumps({"scrobbles": scrobbles}))


def test_anniversary_dates_follow_previous_year_then_five_year_steps() -> None:
    assert daily_mind_radio.anniversary_dates(
        date(2026, 7, 22),
        earliest_year=2007,
    ) == (
        date(2025, 7, 22),
        date(2020, 7, 22),
        date(2015, 7, 22),
        date(2010, 7, 22),
    )
    assert daily_mind_radio.anniversary_dates(
        date(2028, 7, 22),
        earliest_year=2007,
    ) == (
        date(2027, 7, 22),
        date(2022, 7, 22),
        date(2017, 7, 22),
        date(2012, 7, 22),
        date(2007, 7, 22),
    )


def test_anniversary_dates_skip_invalid_february_29() -> None:
    assert (
        daily_mind_radio.anniversary_dates(
            date(2028, 2, 29),
            earliest_year=2007,
        )
        == (date(2012, 2, 29),)
    )


def test_selection_skips_missing_dates_and_uses_one_timestamp(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "lastfm.json"
    write_export(
        export_path,
        [
            export_scrobble(date(2025, 7, 22), "Track 2025"),
            export_scrobble(date(2015, 7, 22), "Track 2015"),
            export_scrobble(date(2010, 1, 1), "Earliest year anchor"),
        ],
    )
    generated_at = datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)
    calls = 0

    def timestamp() -> datetime:
        nonlocal calls
        calls += 1
        return generated_at

    batch = daily_mind_radio.select_daily_mind_radio(
        path=export_path,
        today=date(2026, 7, 22),
        random_timestamp_reader=timestamp,
    )

    assert calls == 1
    assert batch.generated_at is generated_at
    assert batch.missing_dates == (date(2020, 7, 22), date(2010, 7, 22))
    assert [selection.selected_date for selection in batch.selections] == [
        date(2025, 7, 22),
        date(2015, 7, 22),
    ]
    assert [selection.scrobble.track for selection in batch.selections] == [
        "Track 2025",
        "Track 2015",
    ]


def test_no_populated_dates_skips_random_org(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    write_export(
        export_path,
        [export_scrobble(date(2010, 1, 1), "Only track")],
    )

    batch = daily_mind_radio.select_daily_mind_radio(
        path=export_path,
        today=date(2026, 7, 22),
        random_timestamp_reader=lambda: pytest.fail("Random.org should not be called"),
    )

    assert batch.generated_at is None
    assert batch.selections == ()
    assert batch.missing_dates == batch.target_dates


def test_spotify_routine_reuses_liked_match_preference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrobble = blast_from_past.Scrobble(
        track="Selected track",
        artist="Artist",
        album="Expected album",
        timestamp_ms=1,
    )
    selection = blast_from_past.ScrobbleSelection(
        selected_date=date(2025, 7, 22),
        date_index=0,
        scrobbles_on_date=1,
        page=1,
        total_pages=1,
        direction="top down",
        position=1,
        scrobble=scrobble,
    )
    batch = daily_mind_radio.DailyMindRadioBatch(
        generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
        target_dates=(date(2025, 7, 22),),
        missing_dates=(),
        selections=(selection,),
    )
    sp = FakeSpotify()
    query = blast_from_past.spotify_search_query(scrobble)
    sp.search_results[query] = [
        spotify_track(
            "unliked",
            "Selected track",
            "Artist",
            "Expected album",
            100,
        ),
        spotify_track(
            "liked",
            "Selected track - Remastered",
            "Artist",
            "Different album",
            10,
        ),
    ]
    sp.liked_ids = {"liked"}
    monkeypatch.setattr(
        daily_mind_radio,
        "select_daily_mind_radio",
        lambda **_kwargs: batch,
    )

    summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
        sp,  # type: ignore[arg-type]
        "daily",
    )

    assert summary.added == 1
    assert summary.playlist_length_before == 0
    assert summary.playlist_length_after == 1
    assert summary.results[0].match is not None
    assert summary.results[0].match.spotify_id == "liked"
    assert sp.posts == [("playlists/daily/items", {"uris": ["spotify:track:liked"]})]


def test_spotify_routine_avoids_api_calls_when_all_dates_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = daily_mind_radio.DailyMindRadioBatch(
        generated_at=None,
        target_dates=(date(2025, 7, 22),),
        missing_dates=(date(2025, 7, 22),),
        selections=(),
    )
    monkeypatch.setattr(
        daily_mind_radio,
        "select_daily_mind_radio",
        lambda **_kwargs: batch,
    )

    summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
        object(),  # type: ignore[arg-type]
        "daily",
    )

    assert summary.playlist_length_before is None
    assert summary.playlist_length_after is None
    assert summary.results == ()
