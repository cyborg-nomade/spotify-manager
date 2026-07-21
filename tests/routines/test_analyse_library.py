"""Tests for split export-only and live-only library analysis."""

import json
from pathlib import Path

import pytest
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
        assert limit <= 50
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
        retry_base_seconds=120,
        retry_max_seconds=600,
    )

    assert [notice.http_status for notice in notices] == [500, 503]
    assert [notice.delay_seconds for notice in notices] == [120, 240]
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    retries = [item for item in events if item["event"] == "server_retry_scheduled"]
    assert [item["delay_seconds"] for item in retries] == [120, 240]


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
