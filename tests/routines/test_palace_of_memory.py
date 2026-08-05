"""Tests for the Palace of Memory fill routine."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory


BERLIN = ZoneInfo("Europe/Berlin")


def saved_album(index: int) -> dict[str, str]:
    """Return one saved-album mirror entry."""
    return {
        "artist": f"Artist {index}",
        "album": f"Album {index:02d}",
        "uri": f"spotify:album:album-{index}",
    }


def spotify_saved_album(index: int) -> dict[str, object]:
    """Return one Spotify saved-album endpoint item."""
    return {
        "album": {
            "id": f"album-{index}",
            "uri": f"spotify:album:album-{index}",
            "name": f"Album {index:02d}",
            "artists": [{"name": f"Artist {index}"}],
        }
    }


def write_albums(path: Path, count: int = 15) -> None:
    """Write an ordered saved-album mirror."""
    path.write_text(json.dumps([saved_album(index) for index in range(count)]))


def timestamp_ms(year: int, month: int, day: int, hour: int = 12) -> int:
    """Return one Berlin-local Last.fm millisecond timestamp."""
    return int(datetime(year, month, day, hour, tzinfo=BERLIN).timestamp() * 1000)


def raw_scrobble(
    artist: str,
    album: str,
    played_at_ms: int,
) -> dict[str, object]:
    """Return one Last.fm export scrobble."""
    return {
        "artist": artist,
        "album": album,
        "track": "Track",
        "date": played_at_ms,
    }


def write_history(path: Path, album_indexes: range = range(10, 15)) -> None:
    """Write five dates with one saved album on each date."""
    scrobbles = [
        raw_scrobble(
            f"Artist {album_index}",
            f"Album {album_index:02d}",
            timestamp_ms(2010 + offset, 1, 2),
        )
        for offset, album_index in enumerate(album_indexes)
    ]
    path.write_text(json.dumps({"scrobbles": scrobbles}))


class FakeSpotify:
    """Small Spotify stand-in for album, playlist, and search operations."""

    def __init__(self) -> None:
        self.saved_albums = [spotify_saved_album(index) for index in range(15)]
        self.playlist_tracks: list[dict[str, object]] = []
        self.rechecked_playlist_tracks: list[dict[str, object]] | None = None
        self.album_track_map: dict[str, list[dict[str, object]]] = {
            f"album-{index}": [
                {
                    "id": f"track-{index}",
                    "uri": f"spotify:track:track-{index}",
                    "name": f"First Track {index}",
                }
            ]
            for index in range(30)
        }
        self.search_items: list[dict[str, object]] = []
        self.search_calls: list[str] = []
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.get_calls = 0
        self.fail_post = False

    def current_user_saved_albums(
        self,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert limit == palace_of_memory.SAVED_ALBUM_PAGE_SIZE
        items = self.saved_albums[offset : offset + limit]
        return {
            "items": items,
            "total": len(self.saved_albums),
            "next": "next" if offset + len(items) < len(self.saved_albums) else None,
        }

    def _get(self, path: str, limit: int, offset: int) -> dict[str, object]:
        assert path == "playlists/palace/items"
        self.get_calls += 1
        source = self.playlist_tracks
        if self.get_calls > 1 and self.rechecked_playlist_tracks is not None:
            source = self.rechecked_playlist_tracks
        tracks = source[offset : offset + limit]
        return {
            "items": [{"item": track} for track in tracks],
            "total": len(source),
            "next": "next" if offset + len(tracks) < len(source) else None,
        }

    def album_tracks(
        self,
        album_id: str,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert limit == 50
        assert offset == 0
        return {"items": self.album_track_map.get(album_id, [])}

    def search(
        self,
        q: str,
        type: str,  # noqa: A002 - mirrors Spotipy's public method signature
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert type == "album"
        assert limit == palace_of_memory.SPOTIFY_SEARCH_LIMIT
        assert offset == 0
        self.search_calls.append(q)
        return {"albums": {"items": self.search_items}}

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, str]:
        if self.fail_post:
            raise RuntimeError("post failed")
        self.posts.append((path, payload))
        return {"snapshot_id": "snapshot"}


def fixed_random_indexes(
    population_size: int,
    count: int,
) -> blast_from_past.RandomIndexSet:
    """Select the first five dates with a seconds value that wraps."""
    assert population_size == 5
    assert count == 5
    return blast_from_past.RandomIndexSet(
        indexes=(0, 1, 2, 3, 4),
        generated_at=datetime(2026, 8, 4, 10, 47, 52, tzinfo=UTC),
    )


def test_rank_albums_counts_and_breaks_ties_by_album_name() -> None:
    scrobbles = [
        blast_from_past.Scrobble("T1", "Artist", "Zulu", 4),
        blast_from_past.Scrobble("T2", "Artist", "Alpha", 3),
        blast_from_past.Scrobble("T3", "Artist", "Zulu", 2),
        blast_from_past.Scrobble("T4", "Artist", "", 1),
    ]

    ranking = palace_of_memory.rank_albums(scrobbles)

    assert [(item.album, item.scrobbles) for item in ranking] == [
        ("Zulu", 2),
        ("Alpha", 1),
    ]


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("2", 1),
        ("album-2", 1),
        ("spotify:album:album-2", 1),
        ("https://open.spotify.com/album/album-2?si=example", 1),
        ("  shared title  ", 1),
        ("Second Artist - Shared Title", 1),
    ],
)
def test_resolve_alphabetical_start_accepts_supported_references(
    reference: str,
    expected: int,
) -> None:
    albums = (
        YourLibraryAlbum(
            artist="First Artist",
            album="First Album",
            uri="spotify:album:album-1",
        ),
        YourLibraryAlbum(
            artist="Second Artist",
            album="Shared Title",
            uri="spotify:album:album-2",
        ),
        YourLibraryAlbum(
            artist="Third Artist",
            album="Third Album",
            uri="spotify:album:album-3",
        ),
    )

    assert palace_of_memory.resolve_alphabetical_start(albums, reference) == expected


def test_resolve_alphabetical_start_rejects_ambiguous_title() -> None:
    albums = (
        YourLibraryAlbum(
            artist="First Artist",
            album="Shared Title",
            uri="spotify:album:album-1",
        ),
        YourLibraryAlbum(
            artist="Second Artist",
            album="Shared Title",
            uri="spotify:album:album-2",
        ),
    )

    with pytest.raises(
        palace_of_memory.PalaceOfMemoryConfigError,
        match="ambiguous; use a Spotify album id",
    ):
        palace_of_memory.resolve_alphabetical_start(albums, "Shared Title")


def test_historical_selection_uses_seconds_only_and_wraps(tmp_path: Path) -> None:
    history_path = tmp_path / "lastfm.json"
    scrobbles: list[dict[str, object]] = []
    for day in range(1, 6):
        for album_index in range(3):
            scrobbles.extend(
                [
                    raw_scrobble(
                        "Artist",
                        f"Album {album_index}",
                        timestamp_ms(2010, 1, day, 12 + album_index),
                    )
                ]
                * (3 - album_index)
            )
    scrobbles.append(raw_scrobble("Future", "Future Album", timestamp_ms(2026, 1, 1)))
    history_path.write_text(json.dumps({"scrobbles": scrobbles}))

    generated_at, cutoff, available, selections = (
        palace_of_memory.select_historical_albums(
            path=history_path,
            today=date(2026, 8, 4),
            random_index_reader=fixed_random_indexes,
        )
    )

    assert generated_at.second == 52
    assert cutoff == date(2025, 12, 31)
    assert available == 5
    assert {selection.album.album for selection in selections} == {"Album 1"}
    assert {selection.position for selection in selections} == {2}
    assert {selection.albums_on_date for selection in selections} == {3}


def test_dry_run_plans_ten_unique_first_tracks_without_writes(
    tmp_path: Path,
) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    write_albums(albums_path)
    write_history(history_path)
    spotify = FakeSpotify()

    summary = palace_of_memory.fill_palace_of_memory(
        spotify,  # type: ignore[arg-type]
        "palace",
        dry_run=True,
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=state_path,
        log_path=log_path,
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert summary.cutoff_date == date(2025, 12, 31)
    assert summary.alphabetical_start_index == 0
    assert summary.alphabetical_next_index == 5
    assert summary.added == 10
    assert [result.source for result in summary.results] == [
        *("alphabetical" for _ in range(5)),
        *("history" for _ in range(5)),
    ]
    assert [result.first_track.name for result in summary.results] == [
        *(f"First Track {index}" for index in range(5)),
        *(f"First Track {index}" for index in range(10, 15)),
    ]
    assert spotify.posts == []
    assert not state_path.exists()
    assert not log_path.exists()


def test_saved_album_refresh_publishes_live_order_with_backup(tmp_path: Path) -> None:
    albums_path = tmp_path / "albums.json"
    backups_dir = tmp_path / "backups"
    refresh_log = tmp_path / "refresh.jsonl"
    write_albums(albums_path)
    spotify = FakeSpotify()
    spotify.saved_albums.append(spotify_saved_album(15))

    albums, refresh = palace_of_memory.refresh_saved_albums(
        spotify,  # type: ignore[arg-type]
        path=albums_path,
        backups_dir=backups_dir,
        log_path=refresh_log,
    )

    assert len(albums) == 16
    assert refresh.previous == 15
    assert refresh.current == 16
    assert refresh.added == 1
    assert refresh.removed == 0
    assert refresh.persisted is True
    assert refresh.backup_path is not None
    assert Path(refresh.backup_path).exists()
    assert len(json.loads(albums_path.read_text())) == 16
    assert json.loads(refresh_log.read_text())["added"] == 1


def test_real_run_adds_in_order_and_persists_next_cursor(tmp_path: Path) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    write_albums(albums_path)
    write_history(history_path)
    spotify = FakeSpotify()

    summary = palace_of_memory.fill_palace_of_memory(
        spotify,  # type: ignore[arg-type]
        "palace",
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=state_path,
        log_path=log_path,
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert summary.added == 10
    assert spotify.posts == [
        (
            "playlists/palace/items",
            {
                "uris": [
                    *(f"spotify:track:track-{index}" for index in range(5)),
                    *(f"spotify:track:track-{index}" for index in range(10, 15)),
                ]
            },
        )
    ]
    state = json.loads(state_path.read_text())
    assert state["next_alphabetical_index"] == 5
    assert state["last_alphabetical_album_id"] == "album-4"
    assert json.loads(log_path.read_text())["playlist_length_after"] == 10

    spotify.posts.clear()
    second = palace_of_memory.fill_palace_of_memory(
        spotify,  # type: ignore[arg-type]
        "palace",
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=state_path,
        log_path=log_path,
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert second.alphabetical_start_index == 5
    assert [
        result.spotify_album.spotify_id
        for result in second.results[:5]
        if result.spotify_album is not None
    ] == [f"album-{index}" for index in range(5, 10)]


def test_manual_alphabetical_start_overrides_and_replaces_cursor(
    tmp_path: Path,
) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    state_path = tmp_path / "state.json"
    write_albums(albums_path)
    write_history(history_path)
    state_path.write_text(
        json.dumps(
            {
                "next_alphabetical_index": 10,
                "last_alphabetical_album_id": "album-9",
            }
        )
    )
    spotify = FakeSpotify()

    summary = palace_of_memory.fill_palace_of_memory(
        spotify,  # type: ignore[arg-type]
        "palace",
        alphabetical_start="spotify:album:album-2",
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert summary.alphabetical_cursor_overridden is True
    assert summary.alphabetical_start_index == 2
    assert [
        result.spotify_album.spotify_id
        for result in summary.results[:5]
        if result.spotify_album is not None
    ] == [f"album-{index}" for index in range(2, 7)]
    state = json.loads(state_path.read_text())
    assert state["next_alphabetical_index"] == 7
    assert state["last_alphabetical_album_id"] == "album-6"


def test_manual_alphabetical_start_dry_run_does_not_change_cursor(
    tmp_path: Path,
) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    state_path = tmp_path / "state.json"
    write_albums(albums_path)
    write_history(history_path)
    original_state = '{"next_alphabetical_index": 10}'
    state_path.write_text(original_state)

    summary = palace_of_memory.fill_palace_of_memory(
        FakeSpotify(),  # type: ignore[arg-type]
        "palace",
        dry_run=True,
        alphabetical_start="6",
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert summary.alphabetical_start_index == 5
    assert summary.alphabetical_cursor_overridden is True
    assert state_path.read_text() == original_state


def test_set_alphabetical_cursor_persists_next_position_without_playlist_calls(
    tmp_path: Path,
) -> None:
    albums_path = tmp_path / "albums.json"
    state_path = tmp_path / "state.json"
    write_albums(albums_path)
    spotify = FakeSpotify()

    update = palace_of_memory.set_alphabetical_cursor(
        spotify,  # type: ignore[arg-type]
        6,
        albums_path=albums_path,
        state_path=state_path,
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
    )

    assert update.next_index == 5
    assert update.next_album.spotify_id == "album-5"
    assert (
        palace_of_memory._load_cursor(  # noqa: SLF001
            state_path,
            palace_of_memory.load_saved_albums(albums_path),
        )
        == 5
    )
    state = json.loads(state_path.read_text())
    assert state["next_alphabetical_index"] == 5
    assert state["last_alphabetical_album_id"] == "album-4"
    assert spotify.get_calls == 0
    assert spotify.posts == []


def test_real_run_rechecks_playlist_and_avoids_new_duplicate(tmp_path: Path) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    write_albums(albums_path)
    write_history(history_path)
    spotify = FakeSpotify()
    spotify.rechecked_playlist_tracks = [
        {
            "id": "track-0",
            "uri": "spotify:track:track-0",
            "name": "First Track 0",
            "artists": [{"name": "Artist 0"}],
        }
    ]

    summary = palace_of_memory.fill_palace_of_memory(
        spotify,  # type: ignore[arg-type]
        "palace",
        today=date(2026, 8, 4),
        albums_path=albums_path,
        scrobbles_path=history_path,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "log.jsonl",
        album_backups_dir=tmp_path / "album-backups",
        album_refresh_log_path=tmp_path / "refresh.jsonl",
        random_index_reader=fixed_random_indexes,
    )

    assert summary.playlist_length_before == 1
    assert summary.playlist_length_after == 10
    assert summary.results[0].action == "already present"
    assert "spotify:track:track-0" not in spotify.posts[0][1]["uris"]


def test_failed_playlist_write_does_not_advance_cursor(tmp_path: Path) -> None:
    albums_path = tmp_path / "albums.json"
    history_path = tmp_path / "lastfm.json"
    state_path = tmp_path / "state.json"
    write_albums(albums_path)
    write_history(history_path)
    spotify = FakeSpotify()
    spotify.fail_post = True

    with pytest.raises(RuntimeError, match="post failed"):
        palace_of_memory.fill_palace_of_memory(
            spotify,  # type: ignore[arg-type]
            "palace",
            today=date(2026, 8, 4),
            albums_path=albums_path,
            scrobbles_path=history_path,
            state_path=state_path,
            log_path=tmp_path / "log.jsonl",
            album_backups_dir=tmp_path / "album-backups",
            album_refresh_log_path=tmp_path / "refresh.jsonl",
            random_index_reader=fixed_random_indexes,
        )

    assert not state_path.exists()


def test_search_fallback_requires_exact_artist_and_keeps_track_order() -> None:
    spotify = FakeSpotify()
    spotify.search_items = [
        {
            "id": "wrong-artist",
            "uri": "spotify:album:wrong-artist",
            "name": "Historic Album",
            "artists": [{"name": "Someone Else"}],
        },
        {
            "id": "historic",
            "uri": "spotify:album:historic",
            "name": "Historic Album (Remastered)",
            "artists": [{"name": "Historic Artist"}],
        },
    ]
    spotify.album_track_map["historic"] = [
        {"id": "first", "uri": "spotify:track:first", "name": "Zeta"},
        {"id": "second", "uri": "spotify:track:second", "name": "Alpha"},
    ]

    def retry(operation, _description):
        return operation()

    album = palace_of_memory.search_spotify_album(
        spotify,  # type: ignore[arg-type]
        "Historic Artist",
        "Historic Album",
        retry,
    )
    assert album is not None
    track = palace_of_memory.load_first_track(
        spotify,  # type: ignore[arg-type]
        album,
        retry,
    )

    assert album.spotify_id == "historic"
    assert track.name == "Zeta"
