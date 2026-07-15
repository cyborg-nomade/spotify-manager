"""Tests for live-first, restart-safe library synchronization."""

import json
from pathlib import Path

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import analyse_library


def album(album_id: str, name: str | None = None) -> YourLibraryAlbum:
    """Build a local album model."""
    return YourLibraryAlbum(
        artist=f"Artist {album_id}",
        album=name or f"Album {album_id}",
        uri=f"spotify:album:{album_id}",
    )


def track(track_id: str) -> YourLibraryTrack:
    """Build a local track model."""
    return YourLibraryTrack(
        artist=f"Artist {track_id}",
        album=f"Album {track_id}",
        track=f"Track {track_id}",
        uri=f"spotify:track:{track_id}",
    )


def artist(artist_id: str) -> YourLibraryArtist:
    """Build a local artist model."""
    return YourLibraryArtist(
        name=f"Artist {artist_id}",
        uri=f"spotify:artist:{artist_id}",
    )


def saved_album_item(item: YourLibraryAlbum) -> dict:
    """Convert a local album model into a Spotify saved-album item."""
    return {
        "album": {
            "id": item.spotify_id,
            "name": item.album,
            "uri": item.uri,
            "artists": [{"id": f"artist-{item.spotify_id}", "name": item.artist}],
        }
    }


def saved_track_item(item: YourLibraryTrack) -> dict:
    """Convert a local track model into a Spotify saved-track item."""
    return {
        "track": {
            "id": item.spotify_id,
            "name": item.track,
            "uri": item.uri,
            "artists": [{"id": f"artist-{item.spotify_id}", "name": item.artist}],
            "album": {"name": item.album},
        }
    }


def artist_api_item(item: YourLibraryArtist) -> dict:
    """Convert a local artist model into a Spotify artist object."""
    return {"id": item.spotify_id, "name": item.name, "uri": item.uri}


def write_models(path: Path, models: list) -> None:
    """Write a Pydantic model list as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([model.model_dump() for model in models]))


def old_stats_report() -> StatsReport:
    """Return a small valid stats-history report."""
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=1,
            removed_albums=0,
            added_albums=0,
            growth=0,
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=2,
            removed_artists=0,
            added_artists=0,
            growth=0,
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=1,
            removed_tracks=0,
            added_tracks=0,
            growth=0,
        ),
        avg_albums_per_artists=0,
        avg_liked_tracks_per_artists=0,
    )


def prepare_files(
    tmp_path: Path,
    export: YourLibraryFile,
    old_albums: list[YourLibraryAlbum] | None = None,
    old_tracks: list[YourLibraryTrack] | None = None,
    old_artists: list[YourLibraryArtist] | None = None,
) -> analyse_library.LibrarySyncPaths:
    """Create a complete temporary files directory for one sync."""
    paths = analyse_library.LibrarySyncPaths.for_files_dir(tmp_path)
    paths.your_library.write_text(export.model_dump_json())
    write_models(paths.albums_total, old_albums or [album("old")])
    write_models(paths.liked_tracks_legacy, old_tracks or [track("old")])
    write_models(
        paths.artists_total,
        old_artists or [artist("old-followed"), artist("stale")],
    )
    paths.stats_history.write_text(
        json.dumps({"2026.07.13": old_stats_report().model_dump()})
    )
    return paths


class FakeSpotify:
    """Spotify stand-in with configurable pagination and endpoint failures."""

    def __init__(
        self,
        albums: list[dict] | None = None,
        tracks: list[dict] | None = None,
        artists: list[dict] | None = None,
        followed_ids: set[str] | None = None,
        saved_track_ids: set[str] | None = None,
        album_error_status: int | None = None,
        track_error_status: int | None = None,
        track_contains_error_status: int | None = None,
        artist_error_status: int | None = None,
        track_rate_limit_offset: int | None = None,
    ) -> None:
        self.album_items = albums or []
        self.track_items = tracks or []
        self.artist_items = artists or []
        self.followed_ids = followed_ids or set()
        self.saved_track_ids = (
            saved_track_ids
            if saved_track_ids is not None
            else {
                str(item["track"]["id"])
                for item in self.track_items
                if isinstance(item.get("track"), dict) and item["track"].get("id")
            }
        )
        self.album_error_status = album_error_status
        self.track_error_status = track_error_status
        self.track_contains_error_status = track_contains_error_status
        self.artist_error_status = artist_error_status
        self.track_rate_limit_offset = track_rate_limit_offset
        self.album_calls: list[tuple[int, int]] = []
        self.track_calls: list[tuple[int, int]] = []
        self.artist_calls: list[tuple[int, str | None]] = []
        self.contains_calls: list[list[str]] = []
        self.track_contains_calls: list[list[str]] = []

    @staticmethod
    def offset_page(items: list[dict], limit: int, offset: int) -> dict:
        """Return one Spotify-style offset page."""
        page_items = items[offset : offset + limit]
        next_offset = offset + len(page_items)
        return {
            "items": page_items,
            "limit": limit,
            "offset": offset,
            "total": len(items),
            "next": "next" if next_offset < len(items) else None,
        }

    def current_user_saved_albums(self, limit: int, offset: int) -> dict:
        assert limit <= 50
        self.album_calls.append((limit, offset))
        if self.album_error_status is not None:
            raise SpotifyException(self.album_error_status, -1, "albums unavailable")
        return self.offset_page(self.album_items, limit, offset)

    def current_user_saved_tracks(self, limit: int, offset: int) -> dict:
        assert limit <= 10
        self.track_calls.append((limit, offset))
        if self.track_error_status is not None:
            raise SpotifyException(self.track_error_status, -1, "tracks unavailable")
        if self.track_rate_limit_offset == offset:
            self.track_rate_limit_offset = None
            raise SpotifyException(
                429,
                -1,
                "tracks rate limited",
                headers={"Retry-After": "120"},
            )
        return self.offset_page(self.track_items, limit, offset)

    def current_user_followed_artists(
        self,
        limit: int,
        after: str | None,
    ) -> dict:
        assert limit <= 50
        self.artist_calls.append((limit, after))
        if self.artist_error_status is not None:
            raise SpotifyException(self.artist_error_status, -1, "artists unavailable")
        offset = int(after) if after else 0
        page_items = self.artist_items[offset : offset + limit]
        next_offset = offset + len(page_items)
        has_next = next_offset < len(self.artist_items)
        return {
            "artists": {
                "items": page_items,
                "total": len(self.artist_items),
                "next": "next" if has_next else None,
                "cursors": {"after": str(next_offset) if has_next else None},
            }
        }

    def current_user_following_artists(self, artist_ids: list[str]) -> list[bool]:
        assert len(artist_ids) <= 40
        self.contains_calls.append(list(artist_ids))
        return [artist_id in self.followed_ids for artist_id in artist_ids]

    def _get(self, url: str, **kwargs) -> list[bool]:
        assert url == "me/library/contains"
        uris = kwargs["uris"].split(",")
        assert len(uris) <= 40
        self.track_contains_calls.append(uris)
        if self.track_contains_error_status is not None:
            raise SpotifyException(
                self.track_contains_error_status,
                -1,
                "track contains unavailable",
            )
        return [uri.rsplit(":", 1)[-1] in self.saved_track_ids for uri in uris]


def load_ids(path: Path, key: str = "uri") -> list[str]:
    """Return Spotify ids from one generated JSON model list."""
    return [item[key].rsplit(":", 1)[-1] for item in json.loads(path.read_text())]


def test_live_sync_uses_track_limit_and_verified_artist_fallback(tmp_path) -> None:
    export = YourLibraryFile(
        albums=[album("export-old")],
        tracks=[track("export-old")],
        artists=[artist("export-followed"), artist("stale")],
    )
    paths = prepare_files(tmp_path, export)
    export_before = paths.your_library.read_bytes()
    live_albums = [album("live-1"), album("live-2")]
    live_tracks = [track(f"live-{index}") for index in range(12)]
    sp = FakeSpotify(
        albums=[saved_album_item(item) for item in live_albums],
        tracks=[saved_track_item(item) for item in live_tracks],
        artist_error_status=403,
        followed_ids={"old-followed", "export-followed"},
    )
    progress: list[tuple[str, int, int | None, str]] = []

    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        progress_callback=lambda *args: progress.append(args),
        transient_retry_delay_seconds=0,
    )

    assert sp.album_calls == [(50, 0)]
    assert sp.track_calls == [(10, 0), (10, 10), (10, 0), (10, 10)]
    assert sp.track_contains_calls
    assert all(len(batch) <= 40 for batch in sp.track_contains_calls)
    assert sp.contains_calls
    assert all(len(batch) <= 40 for batch in sp.contains_calls)
    assert load_ids(paths.albums_total) == ["live-1", "live-2"]
    assert set(load_ids(paths.liked_tracks_total)) == {
        f"live-{index}" for index in range(12)
    }
    assert set(load_ids(paths.artists_total)) == {
        "old-followed",
        "export-followed",
    }
    assert paths.your_library.read_bytes() == export_before
    assert [resource.source for resource in summary.resources] == [
        "live_api",
        "seeded_live_verified",
        "verified_fallback",
    ]
    assert any(
        item[0] == "tracks" and item[3] == "Verifying seeded tracks"
        for item in progress
    )

    manifest = json.loads((Path(summary.backup_dir) / "manifest.json").read_text())
    assert manifest["changes"]["albums"]["added"]
    assert manifest["changes"]["artists"]["removed"]
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    assert any(event["event"] == "artist_fallback_activated" for event in events)
    assert events[-1]["event"] == "run_completed"


def test_sync_resumes_liked_tracks_after_rate_limit(tmp_path) -> None:
    export = YourLibraryFile(albums=[], tracks=[], artists=[])
    paths = prepare_files(tmp_path, export)
    live_tracks = [track(f"live-{index}") for index in range(12)]
    first_sp = FakeSpotify(
        tracks=[saved_track_item(item) for item in live_tracks],
        artists=[artist_api_item(artist("live-artist"))],
        track_rate_limit_offset=10,
    )

    with pytest.raises(analyse_library.SpotifyRateLimitError):
        analyse_library.analyse_library_routine(
            first_sp,
            paths=paths,
            transient_retry_delay_seconds=0,
        )

    checkpoint = json.loads(paths.checkpoint.read_text())
    assert checkpoint["resources"]["albums"]["status"] == "complete"
    assert checkpoint["resources"]["tracks"]["offset"] == 10
    assert not paths.liked_tracks_total.exists()
    assert load_ids(paths.albums_total) == ["old"]

    second_sp = FakeSpotify(
        tracks=[saved_track_item(item) for item in live_tracks],
        artists=[artist_api_item(artist("live-artist"))],
    )
    analyse_library.analyse_library_routine(
        second_sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert second_sp.album_calls == []
    assert second_sp.track_calls == [(10, 10), (10, 0), (10, 10)]
    assert len(load_ids(paths.liked_tracks_total)) == 12


def test_definite_album_and_track_failures_use_export_fallback(tmp_path) -> None:
    export = YourLibraryFile(
        albums=[album("export-album")],
        tracks=[track("export-track")],
        artists=[artist("live-artist")],
    )
    paths = prepare_files(tmp_path, export)
    sp = FakeSpotify(
        artists=[artist_api_item(artist("live-artist"))],
        album_error_status=403,
        track_error_status=404,
        saved_track_ids={"export-track"},
    )

    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert load_ids(paths.albums_total) == ["export-album"]
    assert load_ids(paths.liked_tracks_total) == ["export-track"]
    assert [resource.source for resource in summary.resources] == [
        "export_fallback",
        "seeded_live_verified_no_discovery",
        "live_api",
    ]


def test_incomplete_live_data_is_not_published(tmp_path) -> None:
    export = YourLibraryFile(albums=[], tracks=[], artists=[])
    paths = prepare_files(tmp_path, export)
    duplicate = saved_album_item(album("duplicate"))
    sp = FakeSpotify(
        albums=[duplicate, duplicate],
        artists=[artist_api_item(artist("live-artist"))],
    )

    with pytest.raises(analyse_library.IncompleteLiveResourceError):
        analyse_library.analyse_library_routine(
            sp,
            paths=paths,
            transient_retry_delay_seconds=0,
        )

    assert load_ids(paths.albums_total) == ["old"]
    assert not paths.liked_tracks_total.exists()


def test_live_followed_artists_are_cursor_paginated(tmp_path) -> None:
    export = YourLibraryFile(albums=[], tracks=[], artists=[])
    paths = prepare_files(tmp_path, export)
    live_artists = [artist_api_item(artist(f"live-{index}")) for index in range(52)]
    sp = FakeSpotify(artists=live_artists)

    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert sp.artist_calls == [(50, None), (50, "50")]
    assert sp.contains_calls == []
    assert len(load_ids(paths.artists_total)) == 52
    assert summary.resources[2].source == "live_api"


def test_artist_502_uses_verified_fallback_after_one_request(tmp_path) -> None:
    export = YourLibraryFile(
        albums=[],
        tracks=[],
        artists=[artist("export-followed")],
    )
    paths = prepare_files(tmp_path, export)
    sp = FakeSpotify(
        artist_error_status=502,
        followed_ids={"export-followed"},
    )
    messages: list[str] = []

    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        echo=messages.append,
        transient_retry_delay_seconds=0,
        transient_max_attempts=3,
    )

    assert sp.artist_calls == [(50, None)]
    assert set(load_ids(paths.artists_total)) == {"export-followed"}
    assert summary.resources[2].source == "verified_fallback"
    assert any("live-verifying" in message for message in messages)
    assert not any("temporarily unavailable" in message for message in messages)


def test_unverifiable_artist_fallback_does_not_publish_any_resource(
    tmp_path,
) -> None:
    export = YourLibraryFile(
        albums=[album("export")],
        tracks=[track("export")],
        artists=[artist("candidate")],
    )
    paths = prepare_files(tmp_path, export)
    sp = FakeSpotify(
        albums=[saved_album_item(album("live"))],
        tracks=[saved_track_item(track("live"))],
        artist_error_status=403,
    )

    def unavailable_contains(_artist_ids):
        raise SpotifyException(403, -1, "contains unavailable")

    sp.current_user_following_artists = unavailable_contains

    with pytest.raises(analyse_library.ArtistVerificationUnavailableError):
        analyse_library.analyse_library_routine(
            sp,
            paths=paths,
            transient_retry_delay_seconds=0,
        )

    assert load_ids(paths.albums_total) == ["old"]
    assert not paths.liked_tracks_total.exists()
    assert set(load_ids(paths.artists_total)) == {"old-followed", "stale"}


def test_seeded_tracks_stop_at_stable_head_pages_despite_total_changes(
    tmp_path,
) -> None:
    seeded_tracks = [track(f"seed-{index}") for index in range(100)]
    export = YourLibraryFile(albums=[], tracks=seeded_tracks, artists=[])
    paths = prepare_files(tmp_path, export, old_tracks=seeded_tracks)
    sp = FakeSpotify(
        tracks=[saved_track_item(item) for item in seeded_tracks],
        artists=[artist_api_item(artist("live-artist"))],
    )
    normal_saved_tracks = sp.current_user_saved_tracks
    reported_totals = iter([100, 101, 99, 100, 101, 99])

    def saved_tracks_with_changing_total(limit: int, offset: int) -> dict:
        page = normal_saved_tracks(limit, offset)
        page["total"] = next(reported_totals)
        return page

    sp.current_user_saved_tracks = saved_tracks_with_changing_total

    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert sp.track_calls == [
        (10, 0),
        (10, 10),
        (10, 20),
        (10, 0),
        (10, 10),
        (10, 20),
    ]
    assert [len(batch) for batch in sp.track_contains_calls] == [40, 40, 20]
    assert len(load_ids(paths.liked_tracks_total)) == 100
    assert summary.resources[1].source == "seeded_live_verified"
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    assert not any(event["event"] == "resource_restarted" for event in events)


def test_v1_checkpoint_migration_preserves_completed_albums(tmp_path) -> None:
    live_album = album("already-fetched")
    seeded_tracks = [track(f"seed-{index}") for index in range(5)]
    export = YourLibraryFile(albums=[], tracks=seeded_tracks, artists=[])
    paths = prepare_files(tmp_path, export, old_tracks=seeded_tracks)
    checkpoint = analyse_library.create_checkpoint(paths, export)
    checkpoint["version"] = 1
    album_state = analyse_library.resource_checkpoint(checkpoint, "albums")
    album_state.update(
        {
            "status": "complete",
            "source": "live_api",
            "offset": 1,
            "fetched": 1,
            "skipped": 0,
            "total": 1,
        }
    )
    track_state = analyse_library.resource_checkpoint(checkpoint, "tracks")
    track_state.update(
        {
            "status": "collecting_live",
            "source": "live_api",
            "offset": 20,
            "fetched": 20,
            "total": 100,
            "restart_count": 2,
        }
    )
    analyse_library.write_models_jsonl(paths.stage("albums"), [live_album])
    analyse_library.write_models_jsonl(paths.stage("tracks"), [track("partial")])
    analyse_library.write_json_atomic(paths.checkpoint, checkpoint)
    sp = FakeSpotify(
        tracks=[saved_track_item(item) for item in seeded_tracks],
        artists=[artist_api_item(artist("live-artist"))],
    )

    analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert sp.album_calls == []
    assert load_ids(paths.albums_total) == ["already-fetched"]
    assert set(load_ids(paths.liked_tracks_total)) == {
        f"seed-{index}" for index in range(5)
    }
    migrated = json.loads(paths.checkpoint.read_text())
    assert migrated["version"] == analyse_library.CHECKPOINT_VERSION
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    migration_event = next(
        event for event in events if event["event"] == "checkpoint_migrated"
    )
    assert migration_event["track_scan_reset"] is True


def test_final_head_scan_catches_a_track_liked_during_verification(tmp_path) -> None:
    seeded_tracks = [track(f"seed-{index}") for index in range(50)]
    newly_liked = track("liked-during-sync")
    export = YourLibraryFile(albums=[], tracks=seeded_tracks, artists=[])
    paths = prepare_files(tmp_path, export, old_tracks=seeded_tracks)
    sp = FakeSpotify(
        tracks=[saved_track_item(item) for item in seeded_tracks],
        artists=[artist_api_item(artist("live-artist"))],
    )
    normal_contains = sp._get

    def contains_then_like_track(url: str, **kwargs) -> list[bool]:
        statuses = normal_contains(url, **kwargs)
        if len(sp.track_contains_calls) == 2:
            sp.track_items.insert(0, saved_track_item(newly_liked))
            sp.saved_track_ids.add(newly_liked.spotify_id)
        return statuses

    sp._get = contains_then_like_track

    analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    assert newly_liked.spotify_id in load_ids(paths.liked_tracks_total)
    assert not any(offset >= 40 for _limit, offset in sp.track_calls)
    events = [json.loads(line) for line in paths.event_log.read_text().splitlines()]
    discovery_events = [
        event for event in events if event["event"] == "track_discovery_completed"
    ]
    assert any(event["new_tracks"] == 1 for event in discovery_events)


def test_restore_library_sync_reinstates_every_generated_file(tmp_path) -> None:
    export = YourLibraryFile(albums=[], tracks=[], artists=[])
    original_albums = [album("old")]
    original_tracks = [track("old")]
    original_artists = [artist("old-followed")]
    paths = prepare_files(
        tmp_path,
        export,
        old_albums=original_albums,
        old_tracks=original_tracks,
        old_artists=original_artists,
    )
    original_stats = paths.stats_history.read_bytes()
    sp = FakeSpotify(
        albums=[saved_album_item(album("new"))],
        tracks=[saved_track_item(track("new"))],
        artists=[artist_api_item(artist("new"))],
    )
    summary = analyse_library.analyse_library_routine(
        sp,
        paths=paths,
        transient_retry_delay_seconds=0,
    )

    restored = analyse_library.restore_library_sync(summary.run_id, paths=paths)

    assert set(restored) == {
        "albums_total_new.json",
        "liked_tracks_total.json",
        "artists_total.json",
        "stats_history.json",
    }
    assert load_ids(paths.albums_total) == ["old"]
    assert not paths.liked_tracks_total.exists()
    assert load_ids(paths.liked_tracks_legacy) == ["old"]
    assert load_ids(paths.artists_total) == ["old-followed"]
    assert paths.stats_history.read_bytes() == original_stats


def test_restore_rejects_path_like_run_ids(tmp_path) -> None:
    paths = analyse_library.LibrarySyncPaths.for_files_dir(tmp_path)
    with pytest.raises(analyse_library.LibrarySyncRestoreError):
        analyse_library.restore_library_sync("../outside", paths=paths)


def test_liked_tracks_loader_prefers_total_and_falls_back_to_legacy(
    monkeypatch,
    tmp_path,
) -> None:
    from spotify_manager import loaders_savers

    total_path = tmp_path / "liked_tracks_total.json"
    legacy_path = tmp_path / "liked_tracks.json"
    write_models(total_path, [track("live")])
    write_models(legacy_path, [track("legacy")])
    monkeypatch.setattr(loaders_savers, "LIKED_TRACKS_TOTAL_PATH", total_path)
    monkeypatch.setattr(loaders_savers, "LIKED_TRACKS_LEGACY_PATH", legacy_path)

    assert [item.spotify_id for item in loaders_savers.load_liked_tracks_file()] == [
        "live"
    ]
    total_path.unlink()
    assert [item.spotify_id for item in loaders_savers.load_liked_tracks_file()] == [
        "legacy"
    ]

    loaders_savers.save_liked_tracks_file([track("saved")])
    assert load_ids(total_path) == ["saved"]
