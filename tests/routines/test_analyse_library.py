"""Tests for split export-only and live-only library analysis."""

import json
from pathlib import Path

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import analyse_library


def album(album_id: str, name: str | None = None) -> YourLibraryAlbum:
    """Build one local album model."""
    return YourLibraryAlbum(
        artist=f"Artist {album_id}",
        album=name or f"Album {album_id}",
        uri=f"spotify:album:{album_id}",
    )


def track(track_id: str) -> YourLibraryTrack:
    """Build one local track model."""
    return YourLibraryTrack(
        artist=f"Artist {track_id}",
        album=f"Album {track_id}",
        track=f"Track {track_id}",
        uri=f"spotify:track:{track_id}",
    )


def artist(artist_id: str) -> YourLibraryArtist:
    """Build one local artist model."""
    return YourLibraryArtist(
        name=f"Artist {artist_id}",
        uri=f"spotify:artist:{artist_id}",
    )


def saved_album_item(item: YourLibraryAlbum) -> dict:
    """Convert a local album into one Spotify saved item."""
    return {
        "album": {
            "id": item.spotify_id,
            "name": item.album,
            "uri": item.uri,
            "artists": [{"name": item.artist}],
        }
    }


def saved_track_item(item: YourLibraryTrack) -> dict:
    """Convert a local track into one Spotify saved item."""
    return {
        "track": {
            "id": item.spotify_id,
            "name": item.track,
            "uri": item.uri,
            "artists": [{"name": item.artist}],
            "album": {"name": item.album},
        }
    }


def artist_api_item(item: YourLibraryArtist) -> dict:
    """Convert a local artist into one Spotify artist object."""
    return {"id": item.spotify_id, "name": item.name, "uri": item.uri}


def paths_for(
    tmp_path: Path,
    mode: analyse_library.AnalysisMode,
) -> analyse_library.LibraryAnalysisPaths:
    """Return isolated paths for one analysis mode."""
    return analyse_library.LibraryAnalysisPaths.for_files_dir(tmp_path, mode)


def ids(path: Path) -> list[str]:
    """Return Spotify ids from one generated model array."""
    return [item["uri"].rsplit(":", 1)[-1] for item in json.loads(path.read_text())]


class FakeSpotify:
    """Spotify stand-in with mutable totals and configurable failures."""

    def __init__(
        self,
        albums: list[YourLibraryAlbum] | None = None,
        tracks: list[YourLibraryTrack] | None = None,
        artists: list[YourLibraryArtist] | None = None,
        album_errors: list[int] | None = None,
        track_rate_limit_offset: int | None = None,
        add_album_during_scan: YourLibraryAlbum | None = None,
        add_artist_during_reconciliation: YourLibraryArtist | None = None,
    ) -> None:
        self.albums = list(albums or [])
        self.tracks = list(tracks or [])
        self.artists = list(artists or [])
        self.album_errors = list(album_errors or [])
        self.track_rate_limit_offset = track_rate_limit_offset
        self.add_album_during_scan = add_album_during_scan
        self.add_artist_during_reconciliation = add_artist_during_reconciliation
        self.album_calls: list[int] = []
        self.track_calls: list[int] = []
        self.artist_calls: list[str | None] = []

    @staticmethod
    def offset_page(items: list[dict], limit: int, offset: int) -> dict:
        """Return one Spotify-style offset page."""
        page_items = items[offset : offset + limit]
        return {
            "items": page_items,
            "offset": offset,
            "limit": limit,
            "total": len(items),
            "next": "next" if offset + len(page_items) < len(items) else None,
        }

    def current_user_saved_albums(self, limit: int, offset: int) -> dict:
        assert limit <= 50
        self.album_calls.append(offset)
        if self.album_errors:
            status = self.album_errors.pop(0)
            raise SpotifyException(status, -1, "temporary album error")
        if (
            self.add_album_during_scan is not None
            and offset > 0
            and self.add_album_during_scan not in self.albums
        ):
            self.albums.insert(0, self.add_album_during_scan)
        return self.offset_page(
            [saved_album_item(item) for item in self.albums],
            limit,
            offset,
        )

    def current_user_saved_tracks(self, limit: int, offset: int) -> dict:
        assert limit <= 10
        self.track_calls.append(offset)
        if self.track_rate_limit_offset == offset:
            self.track_rate_limit_offset = None
            raise SpotifyException(
                429,
                -1,
                "track rate limit",
                headers={"Retry-After": "90"},
            )
        return self.offset_page(
            [saved_track_item(item) for item in self.tracks],
            limit,
            offset,
        )

    def current_user_followed_artists(
        self,
        limit: int,
        after: str | None,
    ) -> dict:
        assert limit == analyse_library.ARTIST_PAGE_LIMIT == 10
        self.artist_calls.append(after)
        if (
            self.add_artist_during_reconciliation is not None
            and len(self.artist_calls) == 2
        ):
            self.artists.append(self.add_artist_during_reconciliation)
        offset = int(after) if after else 0
        page_items = self.artists[offset : offset + limit]
        next_offset = offset + len(page_items)
        has_next = next_offset < len(self.artists)
        return {
            "artists": {
                "items": [artist_api_item(item) for item in page_items],
                "total": len(self.artists),
                "next": "next" if has_next else None,
                "cursors": {"after": str(next_offset) if has_next else None},
            }
        }


def test_export_analysis_only_reads_your_library_and_writes_async_files(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "async")
    export = YourLibraryFile(
        albums=[album("z", "Zebra"), album("b", "The Bends"), album("b", "The Bends")],
        tracks=[track("z"), track("a")],
        artists=[artist("z"), artist("a")],
    )
    paths.your_library.write_text(export.model_dump_json())
    progress: list[tuple[str, int, int | None, str]] = []

    summary = analyse_library.analyse_library_async_routine(
        paths=paths,
        progress_callback=lambda *args: progress.append(args),
    )

    assert paths.albums_total.name == "albums_total_new_async.json"
    assert paths.liked_tracks_total.name == "liked_tracks_total_async.json"
    assert paths.artists_total.name == "artists_total_async.json"
    assert paths.stats_history.name == "stats_history_async.json"
    assert ids(paths.albums_total) == ["b", "z"]
    assert set(ids(paths.liked_tracks_total)) == {"a", "z"}
    assert set(ids(paths.artists_total)) == {"a", "z"}
    assert summary.mode == "async"
    assert {item.source for item in summary.resources} == {"YourLibrary.json"}
    assert summary.resources[0].skipped == 1
    for resource in ("albums", "tracks", "artists"):
        assert [item for item in progress if item[0] == resource][-1][3] == "Complete"
    assert json.loads(paths.checkpoint.read_text())["status"] == "complete"
    assert json.loads(paths.stats_history.read_text())
    assert (Path(summary.backup_dir) / "manifest.json").exists()


def test_export_analysis_can_be_cancelled_and_resumed(tmp_path: Path) -> None:
    paths = paths_for(tmp_path, "async")
    paths.your_library.write_text(
        YourLibraryFile(
            albums=[album("one")],
            tracks=[],
            artists=[],
        ).model_dump_json()
    )

    with pytest.raises(analyse_library.LibraryAnalysisCancelledError):
        analyse_library.analyse_library_async_routine(
            paths=paths,
            cancel_check=lambda: True,
        )

    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    assert events[-1]["event"] == "run_paused"
    assert json.loads(paths.checkpoint.read_text())["status"] == "running"


def test_live_analysis_reconciles_additions_without_restarting_on_new_total(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "sync")
    old_albums = [album(f"a{index:02}") for index in range(55)]
    new_album = album("new")
    new_artist = artist("new")
    spotify = FakeSpotify(
        albums=old_albums,
        tracks=[track(f"t{index:02}") for index in range(12)],
        artists=[artist("one"), artist("two")],
        add_album_during_scan=new_album,
        add_artist_during_reconciliation=new_artist,
    )

    summary = analyse_library.analyse_library_sync_routine(
        spotify,
        paths=paths,
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    assert not paths.your_library.exists()
    assert paths.albums_total.name == "albums_total_new_sync.json"
    assert set(ids(paths.albums_total)) == {
        *(item.spotify_id for item in old_albums),
        "new",
    }
    assert set(ids(paths.liked_tracks_total)) == {f"t{index:02}" for index in range(12)}
    assert set(ids(paths.artists_total)) == {"one", "two", "new"}
    assert spotify.album_calls[:3] == [0, 50, 0]
    assert summary.mode == "sync"
    assert {item.source for item in summary.resources} == {"live_api"}


def test_live_mirror_refresh_publishes_only_canonical_albums_and_tracks(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "mirrors")
    paths.albums_total.write_text(json.dumps([album("old-album").model_dump()]))
    paths.liked_tracks_total.write_text(
        json.dumps([track("old-track").model_dump()])
    )
    spotify = FakeSpotify(
        albums=[album("new-album")],
        tracks=[track("new-track")],
        artists=[artist("must-not-be-read")],
    )

    summary = analyse_library.refresh_live_library_mirrors_routine(
        spotify,
        paths=paths,
        retry_base_seconds=0,
        retry_max_seconds=0,
        full_rebuild=True,
    )

    assert paths.albums_total.name == "albums_total_new.json"
    assert paths.liked_tracks_total.name == "liked_tracks_total.json"
    assert ids(paths.albums_total) == ["new-album"]
    assert ids(paths.liked_tracks_total) == ["new-track"]
    assert not paths.artists_total.exists()
    assert not paths.stats_history.exists()
    assert spotify.artist_calls == []
    assert summary.mode == "mirrors"
    assert [item.resource for item in summary.resources] == ["albums", "tracks"]
    backup_dir = Path(summary.backup_dir)
    assert (backup_dir / "albums.before.json").exists()
    assert (backup_dir / "tracks.before.json").exists()

    restored = analyse_library.restore_library_sync(summary.run_id, paths=paths)

    assert restored == ("albums_total_new.json", "liked_tracks_total.json")
    assert ids(paths.albums_total) == ["old-album"]
    assert ids(paths.liked_tracks_total) == ["old-track"]


def test_live_mirror_incremental_resources_merge_additions_without_removing(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "mirrors")
    known_albums = [album(f"known-album-{index:03}") for index in range(150)]
    paths.albums_total.write_text(
        json.dumps(
            [
                *(item.model_dump() for item in known_albums),
                album("now-unsaved").model_dump(),
            ]
        )
    )
    known_tracks = [track(f"known-{index:03}") for index in range(100)]
    paths.liked_tracks_total.write_text(
        json.dumps(
            [
                *(item.model_dump() for item in known_tracks),
                track("now-unliked").model_dump(),
            ]
        )
    )
    spotify = FakeSpotify(
        albums=[album("new-album"), *known_albums],
        tracks=[track("new"), *known_tracks],
    )

    summary = analyse_library.refresh_live_library_mirrors_routine(
        spotify,
        paths=paths,
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    assert set(ids(paths.albums_total)) == {
        *(item.spotify_id for item in known_albums),
        "new-album",
        "now-unsaved",
    }
    assert set(ids(paths.liked_tracks_total)) == {
        *(item.spotify_id for item in known_tracks),
        "new",
        "now-unliked",
    }
    assert max(spotify.album_calls) == 100
    assert max(spotify.track_calls) == 30
    albums_summary = next(
        item for item in summary.resources if item.resource == "albums"
    )
    tracks_summary = next(
        item for item in summary.resources if item.resource == "tracks"
    )
    assert albums_summary.added == 1
    assert albums_summary.removed == 0
    assert tracks_summary.added == 1
    assert tracks_summary.removed == 0
    checkpoint = json.loads(paths.checkpoint.read_text())
    assert checkpoint["mirror_refresh_mode"] == "incremental"
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    assert any(item["event"] == "incremental_albums_seeded" for item in events)
    assert any(item["event"] == "incremental_tracks_seeded" for item in events)


def test_live_analysis_retries_only_server_errors_with_exponential_delays(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "sync")
    spotify = FakeSpotify(album_errors=[500, 503])
    notices: list[analyse_library.RetryNotice] = []

    def record_retry(notice: analyse_library.RetryNotice) -> bool:
        notices.append(notice)
        return True

    analyse_library.analyse_library_sync_routine(
        spotify,
        paths=paths,
        retry_wait=record_retry,
    )

    assert [notice.http_status for notice in notices] == [500, 503]
    assert [notice.delay_seconds for notice in notices] == [10, 20]
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    retries = [item for item in events if item["event"] == "server_retry_scheduled"]
    assert [item["delay_seconds"] for item in retries] == [10, 20]


def test_live_analysis_retries_connection_resets_with_exponential_delays(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "sync")
    spotify = FakeSpotify(albums=[album("album")])
    original = spotify.current_user_saved_albums
    attempts = 0
    notices: list[analyse_library.RetryNotice] = []

    def flaky_saved_albums(limit: int, offset: int) -> dict:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestsConnectionError(
                "Connection aborted.",
                ConnectionResetError(104, "Connection reset by peer"),
            )
        return original(limit, offset)

    spotify.current_user_saved_albums = flaky_saved_albums  # type: ignore[method-assign]

    analyse_library.analyse_library_sync_routine(
        spotify,
        paths=paths,
        retry_wait=lambda notice: notices.append(notice) is None,
    )

    assert attempts > 1
    assert len(notices) == 1
    assert notices[0].http_status is None
    assert notices[0].delay_seconds == 10
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    retries = [item for item in events if item["event"] == "transport_retry_scheduled"]
    assert len(retries) == 1
    assert retries[0]["error"] == "ConnectionError"


def test_retry_delay_stays_capped_for_many_failures() -> None:
    assert analyse_library.retry_delay(120, 1800, 1_000_000) == 1800


def test_live_analysis_can_quit_cleanly_during_server_retry(tmp_path: Path) -> None:
    paths = paths_for(tmp_path, "sync")
    spotify = FakeSpotify(album_errors=[502])

    with pytest.raises(analyse_library.LibraryAnalysisCancelledError):
        analyse_library.analyse_library_sync_routine(
            spotify,
            paths=paths,
            retry_wait=lambda _notice: False,
        )

    checkpoint = json.loads(paths.checkpoint.read_text())
    assert checkpoint["status"] == "running"
    assert checkpoint["resources"]["albums"]["status"] == "scanning"
    assert not paths.albums_total.exists()
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    assert events[-1]["event"] == "run_paused"


def test_live_analysis_resumes_from_last_saved_page_after_rate_limit(
    tmp_path: Path,
) -> None:
    paths = paths_for(tmp_path, "sync")
    tracks = [track(f"t{index:02}") for index in range(12)]
    first = FakeSpotify(tracks=tracks, track_rate_limit_offset=10)

    with pytest.raises(analyse_library.SpotifyRateLimitError) as exc_info:
        analyse_library.analyse_library_sync_routine(
            first,
            paths=paths,
            retry_base_seconds=0,
            retry_max_seconds=0,
        )

    assert exc_info.value.retry_after_seconds == 90
    checkpoint = json.loads(paths.checkpoint.read_text())
    assert checkpoint["resources"]["albums"]["status"] == "complete"
    assert checkpoint["resources"]["tracks"]["offset"] == 10

    second = FakeSpotify(tracks=tracks)
    analyse_library.analyse_library_sync_routine(
        second,
        paths=paths,
        retry_base_seconds=0,
        retry_max_seconds=0,
    )

    assert second.album_calls == []
    assert second.track_calls[0] == 10
    assert set(ids(paths.liked_tracks_total)) == {f"t{index:02}" for index in range(12)}


def test_restore_searches_both_output_families(tmp_path: Path) -> None:
    paths = paths_for(tmp_path, "async")
    paths.your_library.write_text(
        YourLibraryFile(
            albums=[album("one")],
            tracks=[],
            artists=[],
        ).model_dump_json()
    )
    paths.albums_total.write_text(json.dumps([album("before").model_dump()]))
    summary = analyse_library.analyse_library_async_routine(paths=paths)
    assert ids(paths.albums_total) == ["one"]

    restored = analyse_library.restore_library_sync(summary.run_id, paths=paths)

    assert paths.albums_total.name in restored
    assert ids(paths.albums_total) == ["before"]
