"""Tests for the New Wine from Old Bottles flush."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import new_wine


def raw_release(
    release_id: str,
    name: str,
    *,
    artist_id: str,
    artist_name: str = "Artist",
    album_type: str = "album",
    total_tracks: int = 4,
    release_date: str = "2026-01-01",
) -> dict[str, object]:
    """Build one Spotify release response."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "album_type": album_type,
        "total_tracks": total_tracks,
        "release_date": release_date,
        "artists": [{"id": artist_id, "name": artist_name}],
    }


def raw_track(
    track_id: str,
    name: str,
    release: dict[str, object],
    *,
    artist_id: str,
    artist_name: str = "Artist",
    track_number: int | str = 1,
) -> dict[str, object]:
    """Build one Spotify track response."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "disc_number": 1,
        "track_number": track_number,
        "artists": [{"id": artist_id, "name": artist_name}],
        "album": release,
    }


class FakeSpotify:
    """Small mutable Spotify API simulation for playlist flushes."""

    def __init__(self) -> None:
        self.playlists: dict[str, list[dict[str, object]]] = {
            "new": [],
            "sauv": [],
        }
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.saved_album_ids: set[str] = set()
        self.mutations: list[tuple[str, str, str]] = []
        self.fail_next_delete = False

    def _get(self, path: str, *, limit: int, offset: int):
        playlist_id = path.split("/")[1]
        tracks = self.playlists[playlist_id]
        page = tracks[offset : offset + limit]
        return {
            "items": [{"item": track} for track in page],
            "total": len(tracks),
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    def _post(self, path: str, *, payload: dict[str, object]):
        playlist_id = path.split("/")[1]
        uri = str(payload["uris"][0])  # type: ignore[index]
        track_id = uri.split("spotify:track:")[-1]
        track = next(
            track
            for tracks in self.release_tracks.values()
            for track in tracks
            if track["id"] == track_id
        )
        self.playlists[playlist_id].append(track)
        self.mutations.append(("add", playlist_id, track_id))
        return {}

    def _delete(self, path: str, *, payload: dict[str, object]):
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise RuntimeError("interrupted after add")
        playlist_id = path.split("/")[1]
        uri = str(payload["items"][0]["uri"])  # type: ignore[index]
        track_id = uri.split("spotify:track:")[-1]
        self.playlists[playlist_id] = [
            track for track in self.playlists[playlist_id] if track["id"] != track_id
        ]
        self.mutations.append(("remove", playlist_id, track_id))
        return {}

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    def artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ):
        assert include_groups == "album,single"
        releases = self.artist_releases.get(artist_id, [])
        page = releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(releases) else None,
        }

    def current_user_saved_tracks_contains(self, track_ids: list[str]):
        return [track_id in self.liked_ids for track_id in track_ids]

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def current_user_saved_albums_delete(self, album_ids: list[str]):
        for album_id in album_ids:
            self.saved_album_ids.discard(album_id)
            self.mutations.append(("unsave", "library", album_id))
        return None


def paths(tmp_path: Path) -> dict[str, Path]:
    """Return isolated runtime paths."""
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "albums_path": tmp_path / "albums.json",
        "removed_albums_log_path": tmp_path / "removed.jsonl",
    }


def test_flush_advances_every_snapshotted_album_track(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    first_release = raw_release("r1", "First", artist_id="a1")
    second_release = raw_release("r2", "Second", artist_id="a2")
    first_tracks = [
        raw_track("t1", "One", first_release, artist_id="a1", track_number=1),
        raw_track("t2", "Two", first_release, artist_id="a1", track_number=2),
    ]
    second_tracks = [
        raw_track("u1", "Alpha", second_release, artist_id="a2", track_number=1),
        raw_track("u2", "Beta", second_release, artist_id="a2", track_number=2),
    ]
    spotify.release_tracks = {"r1": first_tracks, "r2": second_tracks}
    spotify.playlists["new"] = [first_tracks[0], second_tracks[0]]

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("album tracks should not prompt"),
        **paths(tmp_path),
    )

    assert summary.processed == 2
    assert summary.advanced == 2
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2", "u2"]
    assert spotify.mutations == [
        ("add", "new", "t2"),
        ("remove", "new", "t1"),
        ("add", "new", "u2"),
        ("remove", "new", "u1"),
    ]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run"]["status"] == "completed"
    assert state["track_progress"]["t2"]["prior_unliked_streak"] == 1


def test_three_consecutive_unliked_tracks_drop_and_unsave_album(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("album", "Drop Me", artist_id="artist")
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids = {"t4"}
    spotify.saved_album_ids = {"album"}
    (tmp_path / "albums.json").write_text(
        json.dumps(
            [
                {
                    "artist": "Artist",
                    "album": "Drop Me",
                    "uri": "spotify:album:album",
                }
            ]
        )
    )

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("drop should not prompt"),
        **paths(tmp_path),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.consecutive_unliked == 3
    assert result.album_liked_tracks == 1
    assert result.album_total_tracks == 4
    assert result.album_unsaved is True
    assert spotify.saved_album_ids == set()
    assert spotify.playlists["new"] == []
    assert json.loads((tmp_path / "albums.json").read_text()) == []
    removed = json.loads((tmp_path / "removed.jsonl").read_text())
    assert removed["action"] == "new_wine_three_consecutive_unliked"


def test_live_like_breaks_the_consecutive_streak(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release("album", "Keep Moving", artist_id="artist")
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 5)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids = {"t2"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("album tracks should not prompt"),
        **paths(tmp_path),
    )

    assert summary.results[0].action == "advance"
    assert summary.results[0].consecutive_unliked == 1
    assert [track["id"] for track in spotify.playlists["new"]] == ["t4"]


def test_dropped_album_remains_saved_when_it_meets_keep_rule(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "album",
        "Still Worth Keeping",
        artist_id="artist",
        total_tracks=6,
    )
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 7)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids = {"t4", "t5", "t6"}
    spotify.saved_album_ids = {"album"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("drop should not prompt"),
        **paths(tmp_path),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.album_liked_tracks == 3
    assert result.album_total_tracks == 6
    assert result.album_unsaved is False
    assert spotify.saved_album_ids == {"album"}
    assert not (tmp_path / "removed.jsonl").exists()


def test_last_album_track_sends_first_track_to_sauvignon(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("album", "Finished", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Last", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"t2"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("album tracks should not prompt"),
        **paths(tmp_path),
    )

    assert summary.sent_to_sauvignon == 1
    assert spotify.playlists["new"] == []
    assert [track["id"] for track in spotify.playlists["sauv"]] == ["t1"]
    assert spotify.mutations == [
        ("add", "sauv", "t1"),
        ("remove", "new", "t2"),
    ]


def test_single_prompts_for_current_year_release_and_starts_at_first_track(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Lead Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "New Album", artist_id="artist")
    old = raw_release(
        "old",
        "Old Album",
        artist_id="artist",
        release_date="2025-01-01",
    )
    single_track = raw_track("s1", "Lead", single, artist_id="artist")
    album_tracks = [
        raw_track("a1", "Opening", album, artist_id="artist", track_number=1),
        raw_track("a2", "Second", album, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [album, single, old]
    spotify.playlists["new"] = [single_track]
    offered: list[tuple[str, ...]] = []

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda _source, candidates: (
            offered.append(tuple(candidate.spotify_id for candidate in candidates))
            or "album"
        ),
        year=2026,
        **paths(tmp_path),
    )

    assert offered == [("album", "single")]
    assert summary.results[0].target_track == "Opening"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]
    assert (
        json.loads((tmp_path / "state.json").read_text())["track_progress"]["a1"][
            "prior_unliked_streak"
        ]
        == 1
    )

    second = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("album tracks should not prompt"),
        year=2026,
        **paths(tmp_path),
    )
    assert second.results[0].consecutive_unliked == 2
    assert [track["id"] for track in spotify.playlists["new"]] == ["a2"]

    third = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("drop should not prompt"),
        year=2026,
        **paths(tmp_path),
    )
    assert third.results[0].action == "drop"
    assert third.results[0].consecutive_unliked == 3
    assert spotify.playlists["new"] == []


def test_selected_release_uses_track_number_not_alphabetical_response(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Lead Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "New Album", artist_id="artist")
    single_track = raw_track("s1", "Lead", single, artist_id="artist")
    album_tracks = [
        raw_track(
            "a2",
            "Alphabetical but second",
            album,
            artist_id="artist",
            track_number="2",
        ),
        raw_track(
            "a1",
            "Zebra opener",
            album,
            artist_id="artist",
            track_number="1",
        ),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [single, album]
    spotify.playlists["new"] = [single_track]

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda _source, _candidates: "album",
        year=2026,
        **paths(tmp_path),
    )

    assert summary.results[0].target_track == "Zebra opener"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]


def test_switching_from_single_to_album_starts_at_album_opener(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Cryogen",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    album = raw_release("album", "The Wow! Signal", artist_id="artist")
    single_track = raw_track("s1", "Cryogen", single, artist_id="artist")
    album_tracks = [
        raw_track(
            "b1",
            "Be With You",
            album,
            artist_id="artist",
            track_number=3,
        ),
        raw_track(
            "s1",
            "Cryogen",
            album,
            artist_id="artist",
            track_number=2,
        ),
        raw_track(
            "a1",
            "The Dark Forest",
            album,
            artist_id="artist",
            track_number=1,
        ),
    ]
    spotify.release_tracks = {
        "single": [single_track],
        "album": album_tracks,
    }
    spotify.artist_releases["artist"] = [single, album]
    spotify.playlists["new"] = [single_track]

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda _source, _candidates: "album",
        year=2026,
        **paths(tmp_path),
    )

    assert summary.results[0].target_track == "The Dark Forest"
    assert [track["id"] for track in spotify.playlists["new"]] == ["a1"]


def test_current_year_release_scan_exhausts_non_chronological_pages() -> None:
    spotify = FakeSpotify()
    older = [
        raw_release(
            f"old-{index}",
            f"Old {index}",
            artist_id="artist",
            release_date=f"20{index:02d}-01-01",
        )
        for index in range(10)
    ]
    current = [
        raw_release(
            "current-1",
            "Current One",
            artist_id="artist",
            album_type="single",
            total_tracks=1,
            release_date="2026-04-17",
        ),
        raw_release(
            "current-2",
            "Current Two",
            artist_id="artist",
            album_type="single",
            total_tracks=1,
            release_date="2026-05-07",
        ),
    ]
    spotify.artist_releases["artist"] = [*older, *current]

    releases = new_wine.current_year_releases(
        spotify,
        "artist",
        2026,
        lambda operation, _description: operation(),
    )

    assert [release.spotify_id for release in releases] == [
        "current-1",
        "current-2",
    ]


def test_single_release_prompt_can_drop_current_release(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Current Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    alternative = raw_release(
        "alternative",
        "Alternative Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
        release_date="2026-02-01",
    )
    track = raw_track("s1", "Current", single, artist_id="artist")
    spotify.release_tracks["single"] = [track]
    spotify.artist_releases["artist"] = [single, alternative]
    spotify.playlists["new"] = [track]
    spotify.liked_ids = {"s1"}
    spotify.saved_album_ids = {"single"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda _source, _candidates: new_wine.CHOICE_DROP,
        year=2026,
        **paths(tmp_path),
    )

    assert summary.results[0].action == "drop"
    assert summary.results[0].drop_reason == "manual_selection"
    assert summary.results[0].album_unsaved is False
    assert spotify.saved_album_ids == {"single"}
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []


def test_lone_current_year_single_is_dropped_automatically(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Only Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
    )
    track = raw_track("s1", "Only Track", single, artist_id="artist")
    spotify.release_tracks["single"] = [track]
    spotify.artist_releases["artist"] = [single]
    spotify.playlists["new"] = [track]
    spotify.saved_album_ids = {"single"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("lone single should auto-drop"),
        year=2026,
        **paths(tmp_path),
    )

    result = summary.results[0]
    assert result.action == "drop"
    assert result.drop_reason == "only_current_year_single"
    assert result.album_unsaved is True
    assert spotify.saved_album_ids == set()
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []
    removed = json.loads((tmp_path / "removed.jsonl").read_text())
    assert removed["action"] == "new_wine_only_current_year_single"


def test_completed_single_is_never_added_to_sauvignon(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Two Track Single",
        artist_id="artist",
        album_type="single",
        total_tracks=2,
    )
    alternative = raw_release(
        "alternative",
        "Another Single",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
        release_date="2026-02-01",
    )
    tracks = [
        raw_track("s1", "First", single, artist_id="artist", track_number=1),
        raw_track("s2", "Last", single, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["single"] = tracks
    spotify.artist_releases["artist"] = [single, alternative]
    spotify.playlists["new"] = [tracks[1]]
    spotify.liked_ids = {"s2"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda _source, _candidates: "single",
        year=2026,
        **paths(tmp_path),
    )

    assert summary.results[0].action == "complete single"
    assert summary.completed_singles == 1
    assert spotify.playlists["new"] == []
    assert spotify.playlists["sauv"] == []


def test_dry_run_reports_unsave_without_mutating_spotify_or_state(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("album", "Dry", artist_id="artist", total_tracks=3)
    tracks = [
        raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        for index in range(1, 4)
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.saved_album_ids = {"album"}

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("drop should not prompt"),
        dry_run=True,
        **paths(tmp_path),
    )

    assert summary.dry_run is True
    assert summary.results[0].album_unsaved is True
    assert spotify.saved_album_ids == {"album"}
    assert [track["id"] for track in spotify.playlists["new"]] == ["t3"]
    assert spotify.mutations == []
    assert not (tmp_path / "state.json").exists()
    assert json.loads((tmp_path / "log.jsonl").read_text())["dry_run"] is True


def test_interrupted_add_before_remove_resumes_without_double_advance(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("album", "Resume", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Second", release, artist_id="artist", track_number=2),
        raw_track("t3", "Third", release, artist_id="artist", track_number=3),
    ]
    spotify.release_tracks["album"] = tracks
    spotify.playlists["new"] = [tracks[0]]
    spotify.fail_next_delete = True
    options = paths(tmp_path)

    with pytest.raises(RuntimeError, match="interrupted"):
        new_wine.flush_new_wine(
            spotify,
            "new",
            "sauv",
            choice_reader=lambda *_args: pytest.fail("album tracks should not prompt"),
            **options,
        )

    assert [track["id"] for track in spotify.playlists["new"]] == ["t1", "t2"]

    summary = new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        choice_reader=lambda *_args: pytest.fail("saved plan should not prompt"),
        **options,
    )

    assert summary.resumed is True
    assert summary.advanced == 1
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2"]
    assert spotify.mutations.count(("add", "new", "t2")) == 1
    assert ("add", "new", "t3") not in spotify.mutations
