"""Tests for the Slow Listening playlist flush."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import slow_listening


def raw_release(
    release_id: str,
    name: str,
    *,
    artist_id: str,
    artist_name: str = "Artist",
    album_type: str = "album",
    total_tracks: int = 2,
    release_date: str = "2020-01-01",
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
    disc_number: int = 1,
    track_number: int = 1,
) -> dict[str, object]:
    """Build one Spotify track response."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "disc_number": disc_number,
        "track_number": track_number,
        "artists": [{"id": artist_id, "name": artist_name}],
        "album": release,
    }


class FakeSpotify:
    """Mutable Spotify simulation for Slow Listening transitions."""

    def __init__(self) -> None:
        self.playlists: dict[str, list[dict[str, object]]] = {"slow": []}
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.saved_album_ids: set[str] = set()
        self.mutations: list[tuple[str, str]] = []
        self.artist_album_calls: list[str] = []
        self.album_track_calls: list[str] = []
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
        self.mutations.append(("add", track_id))
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
        self.mutations.append(("remove", track_id))
        return {}

    def artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ):
        assert include_groups == "album,single"
        self.artist_album_calls.append(artist_id)
        releases = self.artist_releases.get(artist_id, [])
        page = releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(releases) else None,
        }

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        self.album_track_calls.append(album_id)
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }


def paths(tmp_path: Path) -> dict[str, Path]:
    """Return isolated state and log paths."""
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
    }


def default_order(
    _release_date: str,
    releases: tuple[slow_listening.DiscographyRelease, ...],
) -> tuple[str, ...]:
    """Retain the displayed order for equal-date test releases."""
    return tuple(release.spotify_id for release in releases)


def test_flush_advances_only_first_two_playlist_entries(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    releases = [
        raw_release(f"r{index}", f"Release {index}", artist_id=f"a{index}")
        for index in range(1, 4)
    ]
    tracks = [
        [
            raw_track(
                f"t{index}1",
                f"Track {index}.1",
                release,
                artist_id=f"a{index}",
                track_number=1,
            ),
            raw_track(
                f"t{index}2",
                f"Track {index}.2",
                release,
                artist_id=f"a{index}",
                track_number=2,
            ),
        ]
        for index, release in enumerate(releases, start=1)
    ]
    spotify.release_tracks = {
        release["id"]: release_tracks
        for release, release_tracks in zip(releases, tracks, strict=True)
    }
    spotify.artist_releases = {
        f"a{index}": [release] for index, release in enumerate(releases, start=1)
    }
    spotify.playlists["slow"] = [track_list[0] for track_list in tracks]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("no artist should finish"),
        **paths(tmp_path),
    )

    assert summary.total == 2
    assert summary.advanced == 2
    assert [track["id"] for track in spotify.playlists["slow"]] == [
        "t31",
        "t12",
        "t22",
    ]
    assert spotify.mutations == [
        ("add", "t12"),
        ("remove", "t11"),
        ("add", "t22"),
        ("remove", "t21"),
    ]


def test_last_album_track_moves_to_next_studio_ep(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    album = raw_release("album", "First Album", artist_id="artist")
    live = raw_release(
        "live",
        "First Album (Live)",
        artist_id="artist",
        release_date="2021-01-01",
    )
    compilation = raw_release(
        "compilation",
        "The Best Of",
        artist_id="artist",
        album_type="compilation",
        release_date="2021-02-01",
    )
    single = raw_release(
        "single",
        "Standalone",
        artist_id="artist",
        album_type="single",
        total_tracks=1,
        release_date="2021-03-01",
    )
    ep = raw_release(
        "ep",
        "Next Step EP",
        artist_id="artist",
        album_type="single",
        total_tracks=4,
        release_date="2022-01-01",
    )
    album_tracks = [
        raw_track("a1", "First", album, artist_id="artist", track_number=1),
        raw_track("a2", "Last", album, artist_id="artist", track_number=2),
    ]
    ep_tracks = [
        raw_track("e1", "EP Opener", ep, artist_id="artist", track_number=1),
        raw_track("e2", "EP Two", ep, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks = {"album": album_tracks, "ep": ep_tracks}
    spotify.artist_releases["artist"] = [
        ep,
        single,
        compilation,
        live,
        album,
    ]
    spotify.playlists["slow"] = [album_tracks[-1]]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("artist should advance"),
        **paths(tmp_path),
    )

    assert summary.results[0].target_release == "Next Step EP"
    assert summary.results[0].target_track == "EP Opener"
    assert [track["id"] for track in spotify.playlists["slow"]] == ["e1"]
    assert spotify.album_track_calls == ["album", "ep"]


def test_saved_deluxe_edition_wins_over_unsaved_plain_edition(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    plain = raw_release(
        "plain",
        "Shared Album",
        artist_id="artist",
        release_date="2020-01-01",
    )
    deluxe = raw_release(
        "deluxe",
        "Shared Album (Deluxe Edition)",
        artist_id="artist",
        total_tracks=3,
        release_date="2022-01-01",
    )
    plain_tracks = [
        raw_track("p1", "Opening", plain, artist_id="artist", track_number=1),
        raw_track("p2", "Second", plain, artist_id="artist", track_number=2),
    ]
    deluxe_tracks = [
        raw_track("d1", "Opening", deluxe, artist_id="artist", track_number=1),
        raw_track("d2", "Second", deluxe, artist_id="artist", track_number=2),
        raw_track("d3", "Bonus", deluxe, artist_id="artist", track_number=3),
    ]
    spotify.release_tracks = {
        "plain": plain_tracks,
        "deluxe": deluxe_tracks,
    }
    spotify.artist_releases["artist"] = [plain, deluxe]
    spotify.saved_album_ids = {"deluxe"}
    spotify.playlists["slow"] = [deluxe_tracks[0]]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("artist should advance"),
        **paths(tmp_path),
    )

    assert summary.results[0].target_track == "Second"
    assert [track["id"] for track in spotify.playlists["slow"]] == ["d2"]
    assert spotify.album_track_calls == ["deluxe"]


def test_plain_edition_wins_when_no_edition_is_saved() -> None:
    spotify = FakeSpotify()
    plain = raw_release("plain", "Shared Album", artist_id="artist")
    deluxe = raw_release(
        "deluxe",
        "Shared Album (Deluxe Edition)",
        artist_id="artist",
        total_tracks=4,
    )
    spotify.artist_releases["artist"] = [deluxe, plain]

    releases = slow_listening.load_discography(
        spotify,
        "artist",
        lambda operation, _description: operation(),
    )

    assert [release.spotify_id for release in releases] == ["plain"]


def test_equal_date_releases_use_and_save_prompted_order(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    first = raw_release("first", "First", artist_id="artist")
    second = raw_release(
        "second",
        "Alpha",
        artist_id="artist",
        release_date="2021-01-01",
    )
    third = raw_release(
        "third",
        "Beta",
        artist_id="artist",
        release_date="2021-01-01",
    )
    first_track = raw_track("f1", "Only", first, artist_id="artist")
    second_track = raw_track("s1", "Second Opener", second, artist_id="artist")
    third_track = raw_track("t1", "Third Opener", third, artist_id="artist")
    spotify.release_tracks = {
        "first": [first_track],
        "second": [second_track],
        "third": [third_track],
    }
    spotify.artist_releases["artist"] = [first, second, third]
    spotify.playlists["slow"] = [first_track]
    prompted: list[tuple[str, ...]] = []

    def reverse_order(
        _date: str,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> tuple[str, ...]:
        prompted.append(tuple(release.spotify_id for release in releases))
        return tuple(release.spotify_id for release in reversed(releases))

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        reverse_order,
        completion_notifier=lambda _source: pytest.fail("artist should advance"),
        **paths(tmp_path),
    )

    assert prompted == [("second", "third")]
    assert summary.results[0].target_release == "Beta"
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["release_orders"]["artist:2021-01-01"] == ["third", "second"]


def test_advancing_within_album_does_not_prompt_for_future_releases(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    current = raw_release("current", "Current Album", artist_id="artist")
    future_one = raw_release(
        "future-one",
        "Future One",
        artist_id="artist",
        release_date="2021-01-01",
    )
    future_two = raw_release(
        "future-two",
        "Future Two",
        artist_id="artist",
        release_date="2021-01-01",
    )
    current_tracks = [
        raw_track("c1", "Current One", current, artist_id="artist"),
        raw_track(
            "c2",
            "Current Two",
            current,
            artist_id="artist",
            track_number=2,
        ),
    ]
    spotify.release_tracks["current"] = current_tracks
    spotify.artist_releases["artist"] = [future_two, current, future_one]
    spotify.playlists["slow"] = [current_tracks[0]]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        order_reader=lambda *_args: pytest.fail("future releases must not be prompted"),
        completion_notifier=lambda _source: pytest.fail("artist should advance"),
        **paths(tmp_path),
    )

    assert summary.results[0].target_track == "Current Two"
    assert spotify.album_track_calls == ["current"]


def test_skipped_candidate_moves_to_following_track(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "release",
        "Album",
        artist_id="artist",
        total_tracks=3,
    )
    tracks = [
        raw_track("t1", "First", release, artist_id="artist"),
        raw_track(
            "t2",
            "Second",
            release,
            artist_id="artist",
            track_number=2,
        ),
        raw_track(
            "t3",
            "Third",
            release,
            artist_id="artist",
            track_number=3,
        ),
    ]
    spotify.release_tracks["release"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [tracks[0]]
    prompted: list[str] = []

    def choose_candidate(_source, target, _release) -> str:
        prompted.append(target.name)
        if target.spotify_id == "t2":
            return slow_listening.CHOICE_SKIP
        return slow_listening.CHOICE_ADVANCE

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("artist should not finish"),
        action_reader=choose_candidate,
        **paths(tmp_path),
    )

    assert prompted == ["Second", "Third"]
    assert summary.skipped == 0
    assert summary.advanced == 1
    assert summary.results[0].target_track == "Third"
    assert summary.results[0].skipped_candidates == ("Second (Album)",)
    assert [track["id"] for track in spotify.playlists["slow"]] == ["t3"]
    assert spotify.mutations == [("add", "t3"), ("remove", "t1")]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run"]["status"] == "completed"


def test_skipped_candidates_are_remembered_when_run_pauses(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "release",
        "Album",
        artist_id="artist",
        total_tracks=3,
    )
    tracks = [
        raw_track("t1", "First", release, artist_id="artist"),
        raw_track("t2", "Second", release, artist_id="artist", track_number=2),
        raw_track("t3", "Third", release, artist_id="artist", track_number=3),
    ]
    spotify.release_tracks["release"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [tracks[0]]
    first_choices = iter(
        [
            slow_listening.CHOICE_SKIP,
            slow_listening.CHOICE_QUIT,
        ]
    )
    first_prompted: list[str] = []

    paused_summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("artist should not finish"),
        action_reader=lambda _source, target, _release: (
            first_prompted.append(target.name) or next(first_choices)
        ),
        **paths(tmp_path),
    )

    assert paused_summary.paused is True
    assert paused_summary.processed == 0
    assert first_prompted == ["Second", "Third"]
    assert spotify.mutations == []
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_run"]["status"] == "active"
    assert state["active_run"]["entries"][0]["skipped_candidates"] == ["t2"]

    resumed_prompted: list[str] = []
    resumed_summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("artist should not finish"),
        action_reader=lambda _source, target, _release: (
            resumed_prompted.append(target.name) or slow_listening.CHOICE_ADVANCE
        ),
        **paths(tmp_path),
    )

    assert resumed_summary.resumed is True
    assert resumed_prompted == ["Third"]
    assert resumed_summary.results[0].skipped_candidates == ("Second (Album)",)
    assert [track["id"] for track in spotify.playlists["slow"]] == ["t3"]


def test_final_track_removes_artist_and_requests_replacement(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release("last", "Last Album", artist_id="artist")
    final_track = raw_track("last-track", "Finale", release, artist_id="artist")
    spotify.release_tracks["last"] = [final_track]
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [final_track]
    completed: list[str] = []

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda source: completed.append(source.primary_artist_name),
        **paths(tmp_path),
    )

    assert summary.completed_artists == 1
    assert spotify.playlists["slow"] == []
    assert completed == ["Artist"]
    assert spotify.mutations == [("remove", "last-track")]


def test_interrupted_replacement_prompt_is_requested_again(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("last", "Last Album", artist_id="artist")
    final_track = raw_track("last-track", "Finale", release, artist_id="artist")
    spotify.release_tracks["last"] = [final_track]
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [final_track]
    prompts: list[str] = []

    def interrupt_once(source) -> None:
        prompts.append(source.primary_artist_name)
        if len(prompts) == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        slow_listening.flush_slow_listening(
            spotify,
            "slow",
            default_order,
            completion_notifier=interrupt_once,
            **paths(tmp_path),
        )

    assert spotify.playlists["slow"] == []

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=interrupt_once,
        **paths(tmp_path),
    )

    assert summary.resumed is True
    assert summary.completed_artists == 1
    assert prompts == ["Artist", "Artist"]
    assert spotify.mutations == [("remove", "last-track")]


def test_dry_run_logs_but_does_not_mutate_or_prompt(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release("release", "Album", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Second", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["release"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [tracks[0]]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: pytest.fail("dry run cannot prompt"),
        dry_run=True,
        **paths(tmp_path),
    )

    assert summary.dry_run is True
    assert [track["id"] for track in spotify.playlists["slow"]] == ["t1"]
    assert spotify.mutations == []
    assert not (tmp_path / "state.json").exists()
    assert json.loads((tmp_path / "log.jsonl").read_text())["dry_run"] is True


def test_interrupted_add_resumes_without_duplicate_replacement(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release("release", "Album", artist_id="artist")
    tracks = [
        raw_track("t1", "First", release, artist_id="artist", track_number=1),
        raw_track("t2", "Second", release, artist_id="artist", track_number=2),
    ]
    spotify.release_tracks["release"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists["slow"] = [tracks[0]]
    spotify.fail_next_delete = True

    with pytest.raises(RuntimeError, match="interrupted after add"):
        slow_listening.flush_slow_listening(
            spotify,
            "slow",
            default_order,
            completion_notifier=lambda _source: None,
            **paths(tmp_path),
        )

    assert [track["id"] for track in spotify.playlists["slow"]] == ["t1", "t2"]

    summary = slow_listening.flush_slow_listening(
        spotify,
        "slow",
        default_order,
        completion_notifier=lambda _source: None,
        **paths(tmp_path),
    )

    assert summary.resumed is True
    assert [track["id"] for track in spotify.playlists["slow"]] == ["t2"]
    assert spotify.mutations == [
        ("add", "t2"),
        ("remove", "t1"),
    ]


def test_studio_album_named_live_through_this_is_not_filtered() -> None:
    release = raw_release(
        "release",
        "Live Through This",
        artist_id="artist",
    )

    candidate = slow_listening._release_candidate(release, "artist")

    assert candidate is not None
    assert candidate.release_type == "Album"
