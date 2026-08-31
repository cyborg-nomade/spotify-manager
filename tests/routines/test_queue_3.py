"""Tests for the Queue 3 chronological discography routine."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import new_wine
from spotify_manager.routines import queue_3
from spotify_manager.routines import slow_listening


def raw_release(
    release_id: str,
    name: str,
    *,
    artist_id: str,
    artist_name: str = "Artist",
    release_date: str = "2020-01-01",
    total_tracks: int = 2,
) -> dict[str, object]:
    """Build one eligible Spotify album response."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "album_type": "album",
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
    track_number: int = 1,
) -> dict[str, object]:
    """Build one Spotify track with a primary artist and album."""
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
    """Mutable Spotify simulation for Queue 3 and annual imports."""

    def __init__(self) -> None:
        self.owner_id = "listener"
        self.playlists: dict[str, list[dict[str, object]]] = {
            "queue3": [],
            "great-2025": [],
        }
        self.user_playlists: list[dict[str, object]] = [
            self.playlist_summary("queue3", "The Queue 3"),
            self.playlist_summary("great-2025", "Great Discoveries 2025"),
        ]
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.saved_album_ids: set[str] = set()
        self.liked_track_ids: set[str] = set()
        self.mutations: list[tuple[str, str]] = []

    def playlist_summary(
        self,
        playlist_id: str,
        name: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, object]:
        """Build one visible Spotify playlist summary."""
        return {
            "id": playlist_id,
            "name": name,
            "owner": {"id": owner_id or self.owner_id},
            "tracks": {"total": len(self.playlists.get(playlist_id, []))},
        }

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
        raw_uris = payload["uris"]
        assert isinstance(raw_uris, list)
        available = [
            track
            for tracks in [*self.release_tracks.values(), *self.playlists.values()]
            for track in tracks
        ]
        for uri in raw_uris:
            track = next(track for track in available if track["uri"] == uri)
            self.playlists[playlist_id].append(track)
            self.mutations.append(("add", str(track["id"])))
        return {}

    def _delete(self, path: str, *, payload: dict[str, object]):
        playlist_id = path.split("/")[1]
        raw_items = payload["items"]
        assert isinstance(raw_items, list)
        uris = {str(item["uri"]) for item in raw_items}
        removed = [
            track for track in self.playlists[playlist_id] if track["uri"] in uris
        ]
        self.playlists[playlist_id] = [
            track for track in self.playlists[playlist_id] if track["uri"] not in uris
        ]
        self.mutations.extend(("remove", str(track["id"])) for track in removed)
        return {}

    def current_user_playlists(self, *, limit: int, offset: int):
        page = self.user_playlists[offset : offset + limit]
        return {
            "items": page,
            "total": len(self.user_playlists),
            "next": "next" if offset + len(page) < len(self.user_playlists) else None,
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
        releases = self.artist_releases[artist_id]
        page = releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(releases) else None,
        }

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def current_user_saved_albums_add(self, album_ids: list[str]):
        self.saved_album_ids.update(album_ids)

    def current_user_saved_albums_delete(self, album_ids: list[str]):
        self.saved_album_ids.difference_update(album_ids)

    def current_user_saved_tracks_contains(self, track_ids: list[str]):
        return [track_id in self.liked_track_ids for track_id in track_ids]


def paths(tmp_path: Path) -> dict[str, Path]:
    """Return isolated Queue 3 persistence paths."""
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "albums_path": tmp_path / "albums.json",
        "removed_albums_log_path": tmp_path / "removed.jsonl",
    }


def completed_annual_state(tmp_path: Path) -> Path:
    """Persist a completed 2026 import so transition tests stay focused."""
    state_path = tmp_path / "state.json"
    state = queue_3._default_state()
    imports = state["annual_imports"]
    assert isinstance(imports, dict)
    imports["2026"] = {"completed": True, "source_year": 2025}
    queue_3.save_state(state, state_path)
    return state_path


def automatic_transition(*_args: object) -> str:
    """Accept a release boundary in tests."""
    return queue_3.CHOICE_ADVANCE


def test_load_state_migrates_pre_composer_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "version": queue_3.STATE_VERSION,
                "annual_imports": {},
                "release_orders": {},
                "active_run": None,
            }
        )
    )

    assert queue_3.load_state(state_path)["composer_routes"] == {}


def test_saved_composer_route_is_revalidated_with_conservative_matcher() -> None:
    """Queue 3 must discard routes created from a generic `band` match."""
    state = queue_3._default_state()
    routes = state["composer_routes"]
    assert isinstance(routes, dict)
    routes["string-band"] = {
        "artist_name": "The .357 String Band",
        "playlist_id": "dave-setlist",
        "playlist_name": "Dave Matthews Band Setlist",
        "current_track_id": "stillest-hour",
    }
    owned = (
        queue_3.OwnedPlaylist(
            "dave-setlist",
            "2010.10.10_4 - Dave Matthews Band Setlist - Fazenda Maeda",
            20,
        ),
    )

    selected, paused = queue_3._resolve_composer_playlist(
        "string-band",
        "The .357 String Band",
        "stillest-hour",
        "queue3",
        owned,
        state,
        None,
    )

    assert selected is None
    assert paused is False
    assert "string-band" not in routes


def test_flush_advances_only_first_ten_unique_artists(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    first_tracks: list[dict[str, object]] = []
    for index in range(1, 12):
        artist_id = f"artist-{index}"
        release = raw_release(
            f"release-{index}",
            f"Release {index}",
            artist_id=artist_id,
            artist_name=f"Artist {index}",
        )
        tracks = [
            raw_track(
                f"track-{index}-1",
                f"Track {index}.1",
                release,
                artist_id=artist_id,
                artist_name=f"Artist {index}",
                track_number=1,
            ),
            raw_track(
                f"track-{index}-2",
                f"Track {index}.2",
                release,
                artist_id=artist_id,
                artist_name=f"Artist {index}",
                track_number=2,
            ),
        ]
        spotify.artist_releases[artist_id] = [release]
        spotify.release_tracks[f"release-{index}"] = tracks
        first_tracks.append(tracks[0])
    spotify.playlists["queue3"] = [first_tracks[0], *first_tracks]

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("no release boundary should be reached"),
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert summary.total == 10
    assert summary.advanced == 10
    remaining_ids = [str(track["id"]) for track in spotify.playlists["queue3"]]
    assert "track-11-1" in remaining_ids
    assert "track-11-2" not in remaining_ids
    assert "track-1-1" not in remaining_ids
    assert "track-1-2" in remaining_ids


def test_release_boundary_prompts_once_and_saves_kept_album(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    first = raw_release("first", "First", artist_id="artist", total_tracks=2)
    second = raw_release(
        "second",
        "Second",
        artist_id="artist",
        release_date="2021-01-01",
        total_tracks=2,
    )
    first_tracks = [
        raw_track("f1", "First One", first, artist_id="artist", track_number=1),
        raw_track("f2", "First Two", first, artist_id="artist", track_number=2),
    ]
    second_tracks = [
        raw_track("s1", "Second One", second, artist_id="artist", track_number=1),
        raw_track("s2", "Second Two", second, artist_id="artist", track_number=2),
    ]
    spotify.artist_releases["artist"] = [first, second]
    spotify.release_tracks = {"first": first_tracks, "second": second_tracks}
    spotify.playlists["queue3"] = [first_tracks[-1]]
    spotify.liked_track_ids.add("f1")
    transitions: list[tuple[str, str]] = []

    def transition(
        _source,
        current: slow_listening.DiscographyRelease,
        following: slow_listening.DiscographyRelease,
    ) -> str:
        transitions.append((current.spotify_id, following.spotify_id))
        return queue_3.CHOICE_ADVANCE

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        transition,
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert transitions == [("first", "second")]
    assert summary.changed_releases == 1
    assert summary.results[0].album_decision == "keep"
    assert spotify.saved_album_ids == {"first"}
    assert [track["id"] for track in spotify.playlists["queue3"]] == ["s1"]
    albums = json.loads((tmp_path / "albums.json").read_text())
    assert albums[0]["uri"] == "spotify:album:first"


def test_final_track_unsaves_album_and_removes_artist(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "final",
        "Final",
        artist_id="artist",
        total_tracks=1,
    )
    track = raw_track("last", "Last", release, artist_id="artist")
    spotify.artist_releases["artist"] = [release]
    spotify.release_tracks["final"] = [track]
    spotify.playlists["queue3"] = [track]
    spotify.saved_album_ids.add("final")
    (tmp_path / "albums.json").write_text(
        json.dumps(
            [
                {
                    "artist": "Artist",
                    "album": "Final",
                    "uri": "spotify:album:final",
                }
            ]
        )
    )

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        automatic_transition,
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert summary.completed_artists == 1
    assert summary.results[0].album_decision == "remove"
    assert spotify.saved_album_ids == set()
    assert spotify.playlists["queue3"] == []
    assert json.loads((tmp_path / "albums.json").read_text()) == []
    assert (tmp_path / "removed.jsonl").exists()


def test_ineligible_marker_moves_to_first_studio_release(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    marker_release = raw_release(
        "single",
        "Standalone Single",
        artist_id="artist",
        total_tracks=1,
    )
    marker_release["album_type"] = "single"
    eligible = raw_release(
        "album",
        "First Album",
        artist_id="artist",
        release_date="2021-01-01",
    )
    marker = raw_track("single-track", "Single", marker_release, artist_id="artist")
    album_tracks = [
        raw_track("album-1", "Album One", eligible, artist_id="artist"),
        raw_track(
            "album-2",
            "Album Two",
            eligible,
            artist_id="artist",
            track_number=2,
        ),
    ]
    spotify.artist_releases["artist"] = [marker_release, eligible]
    spotify.release_tracks["album"] = album_tracks
    spotify.playlists["queue3"] = [marker]
    transitions: list[tuple[str, str]] = []

    def transition(
        _source,
        current: slow_listening.DiscographyRelease,
        following: slow_listening.DiscographyRelease,
    ) -> str:
        transitions.append((current.spotify_id, following.spotify_id))
        return queue_3.CHOICE_ADVANCE

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        transition,
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert transitions == [("single", "album")]
    assert summary.changed_releases == 1
    assert summary.results[0].album_decision is None
    assert [track["id"] for track in spotify.playlists["queue3"]] == ["album-1"]


def test_artist_without_eligible_releases_is_completed(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    single = raw_release(
        "single",
        "Only Single",
        artist_id="artist",
        total_tracks=1,
    )
    single["album_type"] = "single"
    marker = raw_track("single-track", "Only Single", single, artist_id="artist")
    spotify.artist_releases["artist"] = [single]
    spotify.playlists["queue3"] = [marker]

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("there is no release transition"),
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert summary.completed_artists == 1
    assert summary.results[0].reason == "artist has no eligible studio album or EP"
    assert spotify.playlists["queue3"] == []


def test_annual_import_is_unique_and_persisted(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    existing_release = raw_release("existing-r", "Existing", artist_id="existing")
    new_release = raw_release("new-r", "New", artist_id="new")
    existing = raw_track(
        "existing-t", "Existing", existing_release, artist_id="existing"
    )
    new = raw_track("new-t", "New", new_release, artist_id="new")
    duplicate = raw_track("new-t-2", "New Two", new_release, artist_id="new")
    spotify.playlists["queue3"] = [existing]
    spotify.playlists["great-2025"] = [existing, new, duplicate]
    state = queue_3._default_state()
    state_path = tmp_path / "state.json"
    existing_playlist_track = new_wine._playlist_track({"item": existing})
    assert existing_playlist_track is not None

    tracks, results = queue_3._annual_import(
        spotify,  # type: ignore[arg-type]
        "queue3",
        [existing_playlist_track],
        state,
        owned_playlists=queue_3.load_owned_playlists(
            spotify,  # type: ignore[arg-type]
            lambda operation, _description: operation(),
            "queue3",
        ),
        active_year=2026,
        dry_run=False,
        retry_call=lambda operation, _description: operation(),
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        echo=lambda _line: None,
    )

    assert [result.action for result in results] == ["already present", "added"]
    assert len(tracks) == 2
    assert [track["id"] for track in spotify.playlists["queue3"]] == [
        "existing-t",
        "new-t",
    ]
    persisted = json.loads(state_path.read_text())
    assert persisted["annual_imports"]["2026"]["completed"] is True

    _tracks, repeated = queue_3._annual_import(
        spotify,  # type: ignore[arg-type]
        "queue3",
        tracks,
        state,
        owned_playlists=queue_3.load_owned_playlists(
            spotify,  # type: ignore[arg-type]
            lambda operation, _description: operation(),
            "queue3",
        ),
        active_year=2026,
        dry_run=False,
        retry_call=lambda operation, _description: operation(),
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        echo=lambda _line: None,
    )
    assert repeated == ()


def test_owned_composer_playlist_overrides_discography_and_survives_performer_credit(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    bach_release = raw_release(
        "bach-release",
        "Bach Recording",
        artist_id="bach",
        artist_name="Johann Sebastian Bach",
        total_tracks=3,
    )
    source = raw_track(
        "bach-1",
        "BWV 1",
        bach_release,
        artist_id="bach",
        artist_name="Johann Sebastian Bach",
    )
    performer_release = raw_release(
        "performer-release",
        "Performed Bach",
        artist_id="performer",
        artist_name="The Performer",
        total_tracks=2,
    )
    second = raw_track(
        "bach-2",
        "BWV 2",
        performer_release,
        artist_id="performer",
        artist_name="The Performer",
        track_number=1,
    )
    third = raw_track(
        "bach-3",
        "BWV 3",
        performer_release,
        artist_id="another-performer",
        artist_name="Another Performer",
        track_number=2,
    )
    foreign = raw_track(
        "wrong-next",
        "Wrong copy",
        bach_release,
        artist_id="bach",
        artist_name="Johann Sebastian Bach",
    )
    spotify.playlists.update(
        {
            "queue3": [source],
            "owned-bach": [source, second, third],
            "foreign-bach": [source, foreign],
        }
    )
    spotify.user_playlists.extend(
        [
            spotify.playlist_summary("owned-bach", "All of Bach"),
            spotify.playlist_summary(
                "foreign-bach",
                "Bach chronological works",
                owner_id="someone-else",
            ),
        ]
    )
    state_path = completed_annual_state(tmp_path)

    first = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("composer routes do not prompt by release"),
        active_year=2026,
        **{**paths(tmp_path), "state_path": state_path},
    )

    assert first.results[0].action == "composer playlist"
    assert first.results[0].composer_playlist == "All of Bach"
    assert [track["id"] for track in spotify.playlists["queue3"]] == ["bach-2"]
    persisted = json.loads(state_path.read_text())
    assert persisted["composer_routes"]["bach"]["playlist_id"] == "owned-bach"
    assert persisted["composer_routes"]["bach"]["current_track_id"] == "bach-2"

    second_run = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("composer routes do not load a discography"),
        active_year=2026,
        **{**paths(tmp_path), "state_path": state_path},
    )

    assert second_run.results[0].artist == "Johann Sebastian Bach"
    assert second_run.results[0].source_track == "BWV 2"
    assert second_run.results[0].target_track == "BWV 3"
    assert [track["id"] for track in spotify.playlists["queue3"]] == ["bach-3"]


def test_multiple_owned_composer_playlists_are_prompted_and_persisted(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "glass-release",
        "Glassworks",
        artist_id="glass",
        artist_name="Philip Glass",
    )
    source = raw_track(
        "glass-1",
        "Opening",
        release,
        artist_id="glass",
        artist_name="Philip Glass",
    )
    target = raw_track(
        "glass-2",
        "Closing",
        release,
        artist_id="glass",
        artist_name="Philip Glass",
        track_number=2,
    )
    spotify.playlists.update(
        {
            "queue3": [source],
            "glass-a": [source],
            "glass-b": [source, target],
        }
    )
    spotify.user_playlists.extend(
        [
            spotify.playlist_summary("glass-a", "Philip Glass works"),
            spotify.playlist_summary("glass-b", "Complete Glass"),
        ]
    )
    choices: list[tuple[str, tuple[str, ...]]] = []

    def select(artist: str, candidates: tuple[queue_3.OwnedPlaylist, ...]) -> str:
        choices.append(
            (artist, tuple(candidate.spotify_id for candidate in candidates))
        )
        return "glass-b"

    state_path = completed_annual_state(tmp_path)
    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("composer routes do not prompt by release"),
        composer_playlist_reader=select,
        active_year=2026,
        **{**paths(tmp_path), "state_path": state_path},
    )

    assert choices == [("Philip Glass", ("glass-a", "glass-b"))]
    assert summary.results[0].target_track == "Closing"
    persisted = json.loads(state_path.read_text())
    assert persisted["composer_routes"]["glass"]["playlist_id"] == "glass-b"


def test_final_composer_playlist_track_completes_artist(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    release = raw_release(
        "reich-release",
        "Reich Recording",
        artist_id="reich",
        artist_name="Steve Reich",
        total_tracks=1,
    )
    final = raw_track(
        "reich-final",
        "Final Work",
        release,
        artist_id="reich",
        artist_name="Steve Reich",
    )
    spotify.playlists.update({"queue3": [final], "reich-works": [final]})
    spotify.user_playlists.append(
        spotify.playlist_summary("reich-works", "Chronological Steve Reich")
    )

    summary = queue_3.flush_queue_3(
        spotify,  # type: ignore[arg-type]
        "queue3",
        lambda *_args: pytest.fail("composer routes do not prompt by release"),
        active_year=2026,
        **{
            **paths(tmp_path),
            "state_path": completed_annual_state(tmp_path),
        },
    )

    assert summary.completed_artists == 1
    assert summary.results[0].composer_playlist == "Chronological Steve Reich"
    assert summary.results[0].reason == "last track of the composer playlist"
    assert spotify.playlists["queue3"] == []
