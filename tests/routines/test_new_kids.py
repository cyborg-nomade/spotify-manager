"""Tests for the New Kids on the Block flush."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import new_kids


def raw_release(
    release_id: str,
    name: str,
    *,
    artist_id: str = "artist",
    album_type: str = "album",
    total_tracks: int = 2,
    release_date: str = "2020-01-01",
    popularity: int = 50,
) -> dict[str, object]:
    """Build one full Spotify album object."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "album_type": album_type,
        "total_tracks": total_tracks,
        "release_date": release_date,
        "popularity": popularity,
        "artists": [{"id": artist_id, "name": "Artist"}],
    }


def raw_track(
    track_id: str,
    name: str,
    release: dict[str, object],
    *,
    artist_id: str = "artist",
    track_number: int = 1,
    popularity: int = 40,
) -> dict[str, object]:
    """Build one full Spotify track object."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name,
        "disc_number": 1,
        "track_number": track_number,
        "popularity": popularity,
        "artists": [{"id": artist_id, "name": "Artist"}],
        "album": release,
    }


class FakeSpotify:
    """Mutable Spotify API simulation for New Kids transitions."""

    def __init__(self) -> None:
        self.playlists: dict[str, list[dict[str, object]]] = {
            "new": [],
            "queue": [],
            "great": [],
            "unlucky": [],
            "newfoundland": [],
        }
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.saved_album_ids: set[str] = set()
        self.followed_artist_ids: set[str] = {"artist"}
        self.mutations: list[tuple[str, str, str]] = []
        self.fail_playlist_delete_once: str | None = None

    def _all_tracks(self) -> list[dict[str, object]]:
        return [
            track
            for release_tracks in self.release_tracks.values()
            for track in release_tracks
        ]

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
        track_id = uri.removeprefix("spotify:track:")
        track = next(track for track in self._all_tracks() if track["id"] == track_id)
        self.playlists[playlist_id].append(track)
        self.mutations.append(("add", playlist_id, track_id))
        return {}

    def _delete(
        self,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        uris: str | None = None,
    ):
        if path == "me/library":
            artist_id = str(uris).removeprefix("spotify:artist:")
            self.followed_artist_ids.discard(artist_id)
            self.mutations.append(("unfollow", "library", artist_id))
            return {}
        assert payload is not None
        playlist_id = path.split("/")[1]
        if self.fail_playlist_delete_once == playlist_id:
            self.fail_playlist_delete_once = None
            raise RuntimeError("interrupted after playlist add")
        uri = str(payload["items"][0]["uri"])  # type: ignore[index]
        track_id = uri.removeprefix("spotify:track:")
        self.playlists[playlist_id] = [
            track for track in self.playlists[playlist_id] if track["id"] != track_id
        ]
        self.mutations.append(("remove", playlist_id, track_id))
        return {}

    def artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ):
        assert include_groups == "album,single,compilation"
        releases = self.artist_releases.get(artist_id, [])
        page = releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(releases) else None,
        }

    def albums(self, album_ids: list[str]):
        releases = {
            str(release["id"]): release
            for values in self.artist_releases.values()
            for release in values
        }
        return {"albums": [releases[album_id] for album_id in album_ids]}

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    def artist_top_tracks(self, artist_id: str):
        tracks = [
            track
            for track in self._all_tracks()
            if track["artists"][0]["id"] == artist_id  # type: ignore[index]
        ]
        tracks.sort(key=lambda track: int(track.get("popularity", 0)), reverse=True)
        return {"tracks": tracks[:10]}

    def tracks(self, track_ids: list[str]):
        by_id = {str(track["id"]): track for track in self._all_tracks()}
        return {"tracks": [by_id[track_id] for track_id in track_ids]}

    def current_user_saved_tracks_contains(self, track_ids: list[str]):
        return [track_id in self.liked_ids for track_id in track_ids]

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def current_user_saved_albums_add(self, album_ids: list[str]):
        for album_id in album_ids:
            self.saved_album_ids.add(album_id)
            self.mutations.append(("save", "library", album_id))
        return None

    def current_user_saved_albums_delete(self, album_ids: list[str]):
        for album_id in album_ids:
            self.saved_album_ids.discard(album_id)
            self.mutations.append(("unsave", "library", album_id))
        return None

    def current_user_following_artists(self, artist_ids: list[str]):
        return [artist_id in self.followed_artist_ids for artist_id in artist_ids]


def isolated_paths(tmp_path: Path) -> dict[str, Path]:
    """Return isolated state, log, and mirror paths."""
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "albums_path": tmp_path / "albums.json",
        "artists_path": tmp_path / "artists.json",
        "removed_albums_log_path": tmp_path / "removed.jsonl",
    }


def flush(
    spotify: FakeSpotify,
    tmp_path: Path,
    choice_reader=lambda *_args: pytest.fail("release prompt was unexpected"),
):
    """Run the routine with the standard fake playlist ids."""
    return new_kids.flush_new_kids(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        choice_reader,
        year=2026,
        **isolated_paths(tmp_path),
    )


def test_next_release_options_hides_fallback_tiers_until_needed() -> None:
    """Singles, live albums, and compilations wait for their own tier."""
    releases = tuple(
        new_kids.RankedRelease(
            spotify_id=f"r{tier}",
            uri=f"spotify:album:r{tier}",
            name=f"Tier {tier}",
            release_type="Album",
            release_date="2020-01-01",
            total_tracks=10,
            primary_artist_id="artist",
            primary_artist_name="Artist",
            popularity=50,
            top_track_rank=None,
            tier=tier,
            identity=f"tier{tier}",
            saved=False,
            plain=True,
        )
        for tier in (2, 1, 0, 3)
    )

    assert [release.tier for release in new_kids.next_release_options(releases)] == [0]
    assert [
        release.tier
        for release in new_kids.next_release_options(releases[:2] + releases[3:])
    ] == [1]


def test_catalog_keeps_same_named_album_and_compilation_in_separate_tiers() -> None:
    """Edition collapsing must not erase a preferred studio release."""
    spotify = FakeSpotify()
    album = raw_release("album", "Shared Title", popularity=20)
    compilation = raw_release(
        "compilation",
        "Shared Title",
        album_type="compilation",
        popularity=90,
    )
    spotify.artist_releases["artist"] = [compilation, album]

    catalog = new_kids.load_ranked_catalog(
        spotify,
        "artist",
        lambda operation, _description: operation(),
    )

    assert [(release.spotify_id, release.tier) for release in catalog] == [
        ("album", 0),
        ("compilation", 3),
    ]


def test_flush_adds_next_track_before_removing_current(tmp_path: Path) -> None:
    """A normal advancement is ordered safely and stores streak progress."""
    spotify = FakeSpotify()
    release = raw_release("r1", "First")
    tracks = [
        raw_track("t1", "One", release, track_number=1),
        raw_track("t2", "Two", release, track_number=2),
    ]
    spotify.artist_releases["artist"] = [release]
    spotify.release_tracks["r1"] = tracks
    spotify.playlists["new"] = [tracks[0]]

    summary = flush(spotify, tmp_path)

    assert summary.results[0].action == "advance"
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2"]
    assert spotify.mutations[:2] == [
        ("add", "new", "t2"),
        ("remove", "new", "t1"),
    ]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["artists"]["artist"]["prior_unliked_streak"] == 1


def test_three_unliked_tracks_jump_to_the_next_liked_track(tmp_path: Path) -> None:
    """The refined New Wine rule skips unliked tracks before a later like."""
    spotify = FakeSpotify()
    release = raw_release("r1", "First", total_tracks=5)
    tracks = [
        raw_track(f"t{index}", str(index), release, track_number=index)
        for index in range(1, 6)
    ]
    spotify.artist_releases["artist"] = [release]
    spotify.release_tracks["r1"] = tracks
    spotify.playlists["new"] = [tracks[2]]
    spotify.liked_ids.add("t5")

    summary = flush(spotify, tmp_path)

    result = summary.results[0]
    assert result.action == "advance"
    assert result.consecutive_unliked == 3
    assert result.target_track == "5"
    assert [track["id"] for track in spotify.playlists["new"]] == ["t5"]
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["artists"]["artist"]["prior_unliked_streak"] == 0


def test_release_boundary_prompts_only_with_preferred_release_type(
    tmp_path: Path,
) -> None:
    """A studio album is offered without exposing lower fallback tiers."""
    spotify = FakeSpotify()
    first = raw_release("r1", "First", total_tracks=1, popularity=80)
    second = raw_release("r2", "Second", total_tracks=1, popularity=60)
    single = raw_release(
        "single",
        "Single",
        album_type="single",
        total_tracks=1,
        popularity=99,
    )
    releases = [first, second, single]
    for index, release in enumerate(releases, start=1):
        spotify.release_tracks[str(release["id"])] = [
            raw_track(f"t{index}", f"Track {index}", release)
        ]
    spotify.artist_releases["artist"] = releases
    spotify.playlists["new"] = [spotify.release_tracks["r1"][0]]
    spotify.liked_ids.add("t1")
    shown: list[tuple[new_kids.RankedRelease, ...]] = []

    summary = flush(
        spotify,
        tmp_path,
        choice_reader=lambda _artist, candidates: (
            shown.append(candidates) or candidates[0].spotify_id
        ),
    )

    assert [release.spotify_id for release in shown[0]] == ["r2"]
    assert summary.results[0].action == "next release"
    assert summary.results[0].album_decision == "keep"
    assert "r1" in spotify.saved_album_ids
    assert [track["id"] for track in spotify.playlists["new"]] == ["t2"]


def test_zero_likes_override_saved_release_promotion(tmp_path: Path) -> None:
    """An artist with no liked tracks is unfollowed even with three saves."""
    spotify = FakeSpotify()
    releases = [
        raw_release(
            f"r{index}",
            f"Release {index}",
            total_tracks=1,
            release_date=f"202{index}-01-01",
        )
        for index in range(1, 5)
    ]
    for index, release in enumerate(releases, start=1):
        spotify.release_tracks[f"r{index}"] = [
            raw_track(f"t{index}", f"Track {index}", release)
        ]
    spotify.artist_releases["artist"] = releases
    spotify.playlists["new"] = [spotify.release_tracks["r4"][0]]
    spotify.saved_album_ids.update({"r1", "r2", "r3"})
    state = {
        "version": new_kids.STATE_VERSION,
        "artists": {
            "artist": {
                "artist_name": "Artist",
                "selected_release_ids": ["r1", "r2", "r3", "r4"],
                "selected_release_identities": [
                    "RELEASE1",
                    "RELEASE2",
                    "RELEASE3",
                    "RELEASE4",
                ],
                "completed_release_ids": [],
                "current_release_id": "r4",
                "prior_unliked_streak": 0,
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "great_discoveries_playlists": {},
        "active_run": None,
    }
    new_kids.save_state(state, tmp_path / "state.json")

    summary = flush(spotify, tmp_path)

    assert summary.results[0].action == "unfollowed"
    assert spotify.playlists["great"] == []
    assert spotify.playlists["newfoundland"] == []
    assert spotify.playlists["unlucky"] == []
    assert "artist" not in spotify.followed_artist_ids
    assert ("unfollow", "library", "artist") in spotify.mutations


def test_qualifying_artist_reaches_both_destination_playlists(
    tmp_path: Path,
) -> None:
    """One like plus three saved releases satisfies the four-criteria rule."""
    spotify = FakeSpotify()
    releases = [
        raw_release(
            f"r{index}",
            f"Release {index}",
            total_tracks=1,
            release_date=f"202{index}-01-01",
        )
        for index in range(1, 5)
    ]
    for index, release in enumerate(releases, start=1):
        spotify.release_tracks[f"r{index}"] = [
            raw_track(f"t{index}", f"Track {index}", release)
        ]
    spotify.artist_releases["artist"] = releases
    spotify.playlists["new"] = [spotify.release_tracks["r4"][0]]
    spotify.saved_album_ids.update({"r1", "r2", "r3"})
    spotify.liked_ids.add("t1")
    state = {
        "version": new_kids.STATE_VERSION,
        "artists": {
            "artist": {
                "artist_name": "Artist",
                "selected_release_ids": ["r1", "r2", "r3", "r4"],
                "selected_release_identities": [
                    "RELEASE1",
                    "RELEASE2",
                    "RELEASE3",
                    "RELEASE4",
                ],
                "completed_release_ids": [],
                "current_release_id": "r4",
                "prior_unliked_streak": 0,
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
        "great_discoveries_playlists": {},
        "active_run": None,
    }
    new_kids.save_state(state, tmp_path / "state.json")

    summary = flush(spotify, tmp_path)

    assert summary.results[0].action == "great discovery"
    assert [track["id"] for track in spotify.playlists["great"]] == ["t1"]
    assert [track["id"] for track in spotify.playlists["newfoundland"]] == ["t1"]
    assert "artist" in spotify.followed_artist_ids


def test_interrupted_postfill_resumes_without_advancing_new_artist(
    tmp_path: Path,
) -> None:
    """A Queue 2 transfer resumes in its own phase after a partial mutation."""
    spotify = FakeSpotify()
    current_release = raw_release("r1", "Current")
    current_tracks = [
        raw_track("t1", "One", current_release, track_number=1),
        raw_track("t2", "Two", current_release, track_number=2),
    ]
    queue_release = raw_release(
        "queue-release",
        "Queue Release",
        artist_id="queue-artist",
    )
    queue_track = raw_track(
        "queue-track",
        "Queue Track",
        queue_release,
        artist_id="queue-artist",
    )
    spotify.artist_releases["artist"] = [current_release]
    spotify.release_tracks["r1"] = current_tracks
    spotify.release_tracks["queue-release"] = [queue_track]
    spotify.playlists["new"] = [current_tracks[0]]
    spotify.playlists["queue"] = [queue_track]
    active_state = {
        "version": new_kids.STATE_VERSION,
        "artists": {},
        "great_discoveries_playlists": {},
        "active_run": {
            "run_id": "interrupted-refill-test",
            "playlist_id": "new",
            "status": "active",
            "entries": [
                {
                    "source": {
                        "spotify_id": "t1",
                        "uri": "spotify:track:t1",
                        "name": "One",
                        "primary_artist_id": "artist",
                        "primary_artist_name": "Artist",
                        "release": {
                            "spotify_id": "r1",
                            "uri": "spotify:album:r1",
                            "name": "Current",
                            "release_type": "Album",
                            "release_date": "2020-01-01",
                            "total_tracks": 2,
                            "primary_artist_id": "artist",
                            "primary_artist_name": "Artist",
                        },
                    },
                    "status": "pending",
                    "plan": None,
                }
            ],
            "started_at": "2026-01-01T00:00:00+00:00",
        },
    }
    new_kids.save_state(active_state, tmp_path / "state.json")
    spotify.fail_playlist_delete_once = "queue"

    with pytest.raises(RuntimeError, match="interrupted"):
        flush(spotify, tmp_path)

    interrupted = json.loads((tmp_path / "state.json").read_text())
    assert interrupted["active_run"]["status"] == "refilling"
    assert [track["id"] for track in spotify.playlists["new"]] == [
        "t2",
        "queue-track",
    ]

    summary = flush(spotify, tmp_path)

    assert summary.resumed is True
    assert summary.results == ()
    assert [track["id"] for track in spotify.playlists["new"]] == [
        "t2",
        "queue-track",
    ]
    assert spotify.playlists["queue"] == []
    completed = json.loads((tmp_path / "state.json").read_text())
    assert completed["active_run"] is None
