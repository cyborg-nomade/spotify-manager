"""Tests for the Requeue for a Dream playlist transition."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import slow_listening


def raw_release(
    release_id: str,
    name: str,
    *,
    release_date: str,
    album_type: str = "album",
    total_tracks: int = 2,
) -> dict[str, object]:
    """Build one Spotify release response."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "album_type": album_type,
        "total_tracks": total_tracks,
        "release_date": release_date,
        "artists": [{"id": "artist", "name": "Artist"}],
    }


def raw_track(
    track_id: str,
    name: str,
    release: dict[str, object],
    *,
    track_number: int = 1,
) -> dict[str, object]:
    """Build one Spotify track response."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "disc_number": 1,
        "track_number": track_number,
        "artists": [{"id": "artist", "name": "Artist"}],
        "album": release,
    }


class FakeSpotify:
    """Mutable Spotify simulation for one playlist-head transition."""

    def __init__(self) -> None:
        self.playlist: list[dict[str, object]] = []
        self.releases: list[dict[str, object]] = []
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.saved_album_ids: set[str] = set()
        self.mutations: list[tuple[str, str]] = []
        self.playlist_reads = 0
        self.changed_head: dict[str, object] | None = None
        self.fail_next_delete = False

    def _get(self, _path: str, *, limit: int, offset: int):
        self.playlist_reads += 1
        if self.playlist_reads == 2 and self.changed_head is not None:
            self.playlist.insert(0, self.changed_head)
        page = self.playlist[offset : offset + limit]
        return {
            "items": [{"item": track} for track in page],
            "total": len(self.playlist),
            "next": "next" if offset + len(page) < len(self.playlist) else None,
        }

    def _post(self, _path: str, *, payload: dict[str, object]):
        uri = str(payload["uris"][0])  # type: ignore[index]
        track_id = uri.removeprefix("spotify:track:")
        track = next(
            track
            for tracks in self.release_tracks.values()
            for track in tracks
            if track["id"] == track_id
        )
        self.playlist.append(track)
        self.mutations.append(("add", track_id))
        return {}

    def _delete(self, _path: str, *, payload: dict[str, object]):
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("interrupted after add")
        uri = str(payload["items"][0]["uri"])  # type: ignore[index]
        track_id = uri.removeprefix("spotify:track:")
        self.playlist = [track for track in self.playlist if track["id"] != track_id]
        self.mutations.append(("remove", track_id))
        return {}

    def artist_albums(
        self,
        _artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ):
        assert include_groups == "album,single"
        page = self.releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(self.releases) else None,
        }

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }


def configured_spotify() -> tuple[FakeSpotify, dict[str, object], dict[str, object]]:
    """Return a two-album catalog with one ineligible single between it."""
    spotify = FakeSpotify()
    first = raw_release("r1", "First", release_date="2020-01-01")
    single = raw_release(
        "single",
        "Middle Single",
        release_date="2021-01-01",
        album_type="single",
        total_tracks=1,
    )
    second = raw_release("r2", "Second", release_date="2022-01-01")
    source = raw_track("t1", "Current", first)
    spotify.releases = [second, single, first]
    spotify.release_tracks = {
        "r1": [source],
        "r2": [
            raw_track("t2b", "Second Track", second, track_number=2),
            raw_track("t2a", "First Track", second, track_number=1),
        ],
    }
    spotify.playlist = [source]
    return spotify, first, second


def test_playlist_reference_is_parsed_or_reported() -> None:
    assert requeue_for_a_dream.parse_playlist_id("spotify:playlist:playlistid") == (
        "playlistid"
    )
    with pytest.raises(
        requeue_for_a_dream.RequeueForADreamConfigError,
        match="not configured",
    ):
        requeue_for_a_dream.parse_playlist_id(None)


def test_flush_adds_first_track_of_next_album_before_removing_source(
    tmp_path: Path,
) -> None:
    spotify, _first, _second = configured_spotify()
    log_path = tmp_path / "log.jsonl"

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=log_path,
    )

    assert summary.action == "advance"
    assert summary.target_release == "Second"
    assert summary.target_track == "First Track"
    assert summary.playlist_length_before == 1
    assert summary.playlist_length_after == 1
    assert spotify.mutations == [("add", "t2a"), ("remove", "t1")]
    assert [track["id"] for track in spotify.playlist] == ["t2a"]
    assert json.loads(log_path.read_text(encoding="utf-8"))["action"] == "advance"


def test_flush_drops_artist_at_last_release(tmp_path: Path) -> None:
    spotify, _first, second = configured_spotify()
    source = raw_track("t2a", "First Track", second)
    spotify.playlist = [source]

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "log.jsonl",
    )

    assert summary.action == "drop"
    assert summary.reason == "last eligible release"
    assert summary.target_track is None
    assert spotify.mutations == [("remove", "t2a")]
    assert spotify.playlist == []


def test_flush_does_not_duplicate_an_existing_replacement(tmp_path: Path) -> None:
    spotify, _first, second = configured_spotify()
    target = raw_track("t2a", "First Track", second)
    spotify.playlist.append(target)

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "log.jsonl",
    )

    assert summary.target_already_present is True
    assert summary.playlist_length_after == 1
    assert spotify.mutations == [("remove", "t1")]


def test_flush_resumes_safely_when_removal_failed_after_add(tmp_path: Path) -> None:
    spotify, _first, _second = configured_spotify()
    spotify.fail_next_delete = True
    log_path = tmp_path / "log.jsonl"

    with pytest.raises(RuntimeError, match="interrupted after add"):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=log_path,
        )

    assert spotify.mutations == [("add", "t2a")]
    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=log_path,
    )
    assert summary.target_already_present is True
    assert spotify.mutations == [("add", "t2a"), ("remove", "t1")]
    assert [track["id"] for track in spotify.playlist] == ["t2a"]


def test_dry_run_does_not_mutate_spotify_or_write_a_log(tmp_path: Path) -> None:
    spotify, _first, _second = configured_spotify()
    log_path = tmp_path / "log.jsonl"

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        dry_run=True,
        log_path=log_path,
    )

    assert summary.action == "advance"
    assert summary.dry_run is True
    assert spotify.mutations == []
    assert [track["id"] for track in spotify.playlist] == ["t1"]
    assert not log_path.exists()


def test_flush_aborts_if_playlist_head_changes_before_mutation(tmp_path: Path) -> None:
    spotify, first, _second = configured_spotify()
    spotify.changed_head = raw_track("other", "Other", first)

    with pytest.raises(
        requeue_for_a_dream.RequeueForADreamChangedError,
        match="changed before the update",
    ):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=tmp_path / "log.jsonl",
        )

    assert spotify.mutations == []


def test_empty_playlist_is_a_no_op(tmp_path: Path) -> None:
    spotify = FakeSpotify()

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "log.jsonl",
    )

    assert summary.action == "empty"
    assert summary.playlist_length_before == 0
    assert summary.playlist_length_after == 0
    assert spotify.mutations == []


def test_flush_reports_playlist_discography_and_track_loading_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify, _first, _second = configured_spotify()

    monkeypatch.setattr(
        requeue_for_a_dream.new_wine,
        "load_playlist_tracks",
        lambda *_args: (_ for _ in ()).throw(
            requeue_for_a_dream.new_wine.NewWineError("playlist failed")
        ),
    )
    with pytest.raises(requeue_for_a_dream.RequeueForADreamError, match="playlist"):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=tmp_path / "log.jsonl",
        )

    monkeypatch.undo()
    spotify, _first, _second = configured_spotify()
    monkeypatch.setattr(
        requeue_for_a_dream.slow_listening,
        "load_discography",
        lambda *_args: (_ for _ in ()).throw(
            slow_listening.SlowListeningError("discography failed")
        ),
    )
    with pytest.raises(requeue_for_a_dream.RequeueForADreamError, match="discography"):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=tmp_path / "log.jsonl",
        )

    monkeypatch.undo()
    spotify, _first, _second = configured_spotify()
    monkeypatch.setattr(
        requeue_for_a_dream.slow_listening,
        "load_release_tracks",
        lambda *_args: (_ for _ in ()).throw(
            slow_listening.SlowListeningError("tracks failed")
        ),
    )
    with pytest.raises(requeue_for_a_dream.RequeueForADreamError, match="tracks"):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=tmp_path / "log.jsonl",
        )


def test_flush_skips_ineligible_current_or_empty_next_release(
    tmp_path: Path,
) -> None:
    spotify, first, _second = configured_spotify()
    unknown = raw_release("unknown", "Unknown", release_date="2019-01-01")
    spotify.playlist = [raw_track("unknown-track", "Unknown", unknown)]

    ineligible = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "ineligible.jsonl",
    )

    assert ineligible.action == "skip"
    assert "not an eligible" in str(ineligible.reason)

    spotify, _first, _second = configured_spotify()
    spotify.release_tracks["r2"] = []
    no_tracks = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "empty-release.jsonl",
    )
    assert no_tracks.action == "skip"
    assert no_tracks.target_release == "Second"
    assert "no playable tracks" in str(no_tracks.reason)
    assert first["name"] == "First"


def test_flush_emits_progress_and_wraps_recheck_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify, _first, _second = configured_spotify()
    progress: list[str] = []

    summary = requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        log_path=tmp_path / "log.jsonl",
        progress_callback=progress.append,
    )

    assert summary.action == "advance"
    assert progress == [
        "Loading Requeue for a Dream",
        "Loading Artist's discography",
        "Loading Second",
        "Rechecking the playlist head",
    ]

    spotify, _first, _second = configured_spotify()
    original = requeue_for_a_dream.new_wine.load_playlist_tracks
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise requeue_for_a_dream.new_wine.NewWineError("recheck failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        requeue_for_a_dream.new_wine,
        "load_playlist_tracks",
        fail_second,
    )
    with pytest.raises(requeue_for_a_dream.RequeueForADreamError, match="recheck"):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=tmp_path / "second.jsonl",
        )


def test_log_write_failure_is_reported(tmp_path: Path) -> None:
    spotify, _first, _second = configured_spotify()
    blocked = tmp_path / "blocked"
    blocked.write_text("file")

    with pytest.raises(
        requeue_for_a_dream.RequeueForADreamLogError,
        match="Could not write",
    ):
        requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            "playlist",
            log_path=blocked / "log.jsonl",
        )
