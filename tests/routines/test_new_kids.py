"""Tests for the New Kids on the Block flush."""

import json
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
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
    scrobbles_path = tmp_path / "scrobbles.json"
    if not scrobbles_path.exists():
        scrobbles_path.write_text(json.dumps({"scrobbles": []}))
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "albums_path": tmp_path / "albums.json",
        "artists_path": tmp_path / "artists.json",
        "removed_albums_log_path": tmp_path / "removed.jsonl",
        "scrobbles_path": scrobbles_path,
    }


def write_played_release_history(
    tmp_path: Path,
    release_tracks: list[list[dict[str, object]]],
    *,
    year: int = 2026,
    liked_track_ids: set[str] | None = None,
) -> Path:
    """Write three scrobbles per release plus every requested liked track."""
    liked_ids = liked_track_ids or set()
    records: list[dict[str, object]] = []
    timestamp_ms = int(datetime(year, 6, 1, tzinfo=UTC).timestamp() * 1000)
    for tracks in release_tracks:
        selected = list(tracks[:3])
        selected_ids = {str(track["id"]) for track in selected}
        selected.extend(
            track
            for track in tracks
            if str(track["id"]) in liked_ids and str(track["id"]) not in selected_ids
        )
        for track in selected:
            album = track["album"]
            assert isinstance(album, dict)
            records.append(
                {
                    "artist": "Artist",
                    "track": track["name"],
                    "album": album["name"],
                    "date": timestamp_ms,
                }
            )
            timestamp_ms += 1_000
    path = tmp_path / "scrobbles.json"
    path.write_text(json.dumps({"scrobbles": records}))
    return path


def seed_artist(
    spotify: FakeSpotify,
    artist_id: str,
    *,
    release_count: int = 1,
    tracks_per_release: int = 2,
) -> list[list[dict[str, object]]]:
    """Add a compact primary-artist catalog to the Spotify simulation."""
    releases: list[dict[str, object]] = []
    seeded_tracks: list[list[dict[str, object]]] = []
    for release_index in range(1, release_count + 1):
        release_id = f"{artist_id}-r{release_index}"
        release = raw_release(
            release_id,
            f"{artist_id} Release {release_index}",
            artist_id=artist_id,
            total_tracks=tracks_per_release,
            release_date=f"202{release_index}-01-01",
        )
        tracks = [
            raw_track(
                f"{artist_id}-r{release_index}-t{track_index}",
                f"{artist_id} Track {release_index}.{track_index}",
                release,
                artist_id=artist_id,
                track_number=track_index,
            )
            for track_index in range(1, tracks_per_release + 1)
        ]
        releases.append(release)
        seeded_tracks.append(tracks)
        spotify.release_tracks[release_id] = tracks
    spotify.artist_releases[artist_id] = releases
    return seeded_tracks


def flush(
    spotify: FakeSpotify,
    tmp_path: Path,
    choice_reader=lambda *_args: pytest.fail("release prompt was unexpected"),
    **kwargs: object,
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
        **kwargs,
    )


def test_annual_scrobble_index_uses_only_the_requested_calendar_year(
    tmp_path: Path,
) -> None:
    """The same release heard outside the active year does not count."""
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "scrobbles": [
                    {
                        "artist": "Artist",
                        "track": "Current",
                        "album": "Album (Deluxe)",
                        "date": int(
                            datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000
                        ),
                    },
                    {
                        "artist": "Artist",
                        "track": "Previous",
                        "album": "Album",
                        "date": int(
                            datetime(2025, 12, 31, tzinfo=UTC).timestamp() * 1000
                        ),
                    },
                ]
            }
        )
    )

    index = new_kids.load_annual_scrobble_index(path, year=2026)

    assert index == {("artist", "album"): frozenset({"current"})}


def test_played_release_requires_three_tracks_and_every_liked_track() -> None:
    """Three scrobbles are insufficient when another liked track is unheard."""
    release = new_kids.RankedRelease(
        spotify_id="release",
        uri="spotify:album:release",
        name="Album",
        release_type="Album",
        release_date="2026-01-01",
        total_tracks=4,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        popularity=50,
        top_track_rank=1,
        tier=0,
        identity="album",
        saved=False,
        plain=True,
    )
    tracks = tuple(
        new_kids.CatalogTrack(
            spotify_id=f"t{index}",
            uri=f"spotify:track:t{index}",
            name=f"Track {index}",
            disc_number=1,
            track_number=index,
            primary_artist_id="guest" if index == 4 else "artist",
            primary_artist_name="Guest" if index == 4 else "Artist",
        )
        for index in range(1, 5)
    )
    annual_scrobbles = {
        ("artist", "album"): frozenset({"track 1", "track 2", "track 3"})
    }

    assert new_kids.release_was_played_this_year(
        release,
        tracks,
        {"t1": True, "t2": False, "t3": False, "t4": False},
        annual_scrobbles,
    )
    assert not new_kids.release_was_played_this_year(
        release,
        tracks,
        {"t1": True, "t2": False, "t3": False, "t4": True},
        annual_scrobbles,
    )
    assert new_kids.release_was_played_this_year(
        release,
        tracks,
        {"t1": True, "t2": False, "t3": False, "t4": True},
        {
            **annual_scrobbles,
            ("guest", "album"): frozenset({"track 4"}),
        },
    )


def test_flush_refreshes_history_before_offering_releases(tmp_path: Path) -> None:
    """A release completed in the live delta must not reappear in the prompt."""
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "artist", release_count=3, tracks_per_release=3)
    spotify.playlists["new"] = [tracks[2][-1]]
    spotify.liked_ids.update(str(track["id"]) for track in tracks[0])
    timestamp = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
    (tmp_path / "scrobbles.json").write_text(
        json.dumps(
            {
                "username": "listener",
                "scrobbles": [
                    {
                        "artist": "Artist",
                        "track": tracks[0][0]["name"],
                        "album": tracks[0][0]["album"]["name"],  # type: ignore[index]
                        "date": timestamp * 1000,
                    }
                ],
            }
        )
    )

    class LiveHistory:
        def recent_tracks(
            self,
            *,
            from_timestamp: int,
            to_timestamp: int,
            limit: int = 200,
        ) -> tuple[LastFmRecentTrack, ...]:
            assert from_timestamp == timestamp
            assert to_timestamp >= from_timestamp
            assert limit == 200
            return tuple(
                LastFmRecentTrack(
                    artist="Artist",
                    track=str(track["name"]),
                    album=str(track["album"]["name"]),  # type: ignore[index]
                    timestamp_seconds=timestamp + index,
                )
                for index, track in enumerate(tracks[0][1:], start=1)
            )

    offered: list[tuple[str, ...]] = []

    def choose(_artist: str, releases: tuple[new_kids.RankedRelease, ...]) -> str:
        offered.append(tuple(release.spotify_id for release in releases))
        return releases[0].spotify_id

    summary = flush(
        spotify,
        tmp_path,
        choose,
        lastfm=LiveHistory(),
        lastfm_username="listener",
    )

    assert offered == [("artist-r2",)]
    assert summary.results[0].target_release == "artist Release 2"
    saved = json.loads((tmp_path / "scrobbles.json").read_text())
    assert len(saved["scrobbles"]) == 3


def test_queue_2_refreshes_history_before_touching_playlists(tmp_path: Path) -> None:
    """Queue 2 shares the same live-history prerequisite as New Kids."""
    spotify = FakeSpotify()
    timestamp = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
    (tmp_path / "scrobbles.json").write_text(
        json.dumps(
            {
                "username": "listener",
                "scrobbles": [
                    {
                        "artist": "Artist",
                        "track": "Track",
                        "album": "Release",
                        "date": timestamp * 1000,
                    }
                ],
            }
        )
    )

    class CurrentHistory:
        def recent_tracks(
            self,
            *,
            from_timestamp: int,
            to_timestamp: int,
            limit: int = 200,
        ) -> tuple[LastFmRecentTrack, ...]:
            assert from_timestamp == timestamp
            assert to_timestamp >= from_timestamp
            assert limit == 200
            return ()

    progress: list[str] = []
    summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        year=2026,
        lastfm=CurrentHistory(),
        lastfm_username="listener",
        progress_callback=lambda _done, _total, detail: progress.append(detail),
        **isolated_paths(tmp_path),
    )

    assert summary.results == ()
    assert progress[0] == "Refreshing Last.fm release history"
    assert spotify.mutations == []


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
    tracks = seed_artist(spotify, "artist", release_count=4, tracks_per_release=3)
    spotify.playlists["new"] = [tracks[3][-1]]
    spotify.saved_album_ids.update({"artist-r1", "artist-r2", "artist-r3"})
    write_played_release_history(tmp_path, tracks)
    state = {
        "version": new_kids.STATE_VERSION,
        "artists": {
            "artist": {
                "artist_name": "Artist",
                "selected_release_ids": ["stale-state-must-not-decide-progress"],
                "selected_release_identities": [
                    "stale-state-must-not-decide-progress",
                ],
                "completed_release_ids": [],
                "current_release_id": "artist-r4",
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
    tracks = seed_artist(spotify, "artist", release_count=4, tracks_per_release=3)
    spotify.playlists["new"] = [tracks[3][-1]]
    spotify.saved_album_ids.update({"artist-r1", "artist-r2", "artist-r3"})
    spotify.liked_ids.add("artist-r1-t1")
    write_played_release_history(
        tmp_path,
        tracks,
        liked_track_ids=spotify.liked_ids,
    )
    state = {
        "version": new_kids.STATE_VERSION,
        "artists": {
            "artist": {
                "artist_name": "Artist",
                "selected_release_ids": ["stale"],
                "selected_release_identities": ["stale"],
                "completed_release_ids": [],
                "current_release_id": "artist-r4",
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
    assert [track["id"] for track in spotify.playlists["great"]] == ["artist-r1-t1"]
    assert [track["id"] for track in spotify.playlists["newfoundland"]] == [
        "artist-r1-t1"
    ]
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


def test_queue_2_fills_new_kids_then_advances_only_ten_artists(
    tmp_path: Path,
) -> None:
    """The normal Queue 2 run respects New Kids priority and its daily limit."""
    spotify = FakeSpotify()
    for index in range(8):
        spotify.playlists["new"].append(seed_artist(spotify, f"new-{index}")[0][0])
    queue_tracks = [seed_artist(spotify, f"queue-{index}")[0][0] for index in range(14)]
    spotify.playlists["queue"] = list(queue_tracks)

    summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        year=2026,
        **isolated_paths(tmp_path),
    )

    assert summary.new_kids_length_before == 8
    assert summary.new_kids_length_after == 10
    assert len(summary.prefill) == 2
    assert len(summary.results) == new_kids.QUEUE_2_DAILY_LIMIT
    assert summary.queue_length_before == 14
    assert summary.queue_length_after == 12
    assert [result.artist for result in summary.results] == ["Artist"] * 10
    assert [track["id"] for track in spotify.playlists["new"][-2:]] == [
        "queue-0-r1-t1",
        "queue-1-r1-t1",
    ]
    assert [track["id"] for track in spotify.playlists["queue"]] == [
        "queue-12-r1-t1",
        "queue-13-r1-t1",
        *[f"queue-{index}-r1-t2" for index in range(2, 12)],
    ]


def test_queue_2_dry_run_excludes_simulated_new_kids_transfers(
    tmp_path: Path,
) -> None:
    """A dry run reviews the queue left after its simulated prefill."""
    spotify = FakeSpotify()
    for index in range(9):
        spotify.playlists["new"].append(seed_artist(spotify, f"new-{index}")[0][0])
    first = seed_artist(spotify, "first")[0][0]
    second = seed_artist(spotify, "second")[0][0]
    spotify.playlists["queue"] = [first, second]

    summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        dry_run=True,
        year=2026,
        **isolated_paths(tmp_path),
    )

    assert summary.new_kids_length_after == 10
    assert summary.queue_length_after == 1
    assert len(summary.prefill) == 1
    assert [result.source_track for result in summary.results] == ["second Track 1.1"]
    assert [track["id"] for track in spotify.playlists["queue"]] == [
        "first-r1-t1",
        "second-r1-t1",
    ]
    assert spotify.mutations == []
    assert not (tmp_path / "state.json").exists()


def test_queue_2_progress_carries_into_new_kids(tmp_path: Path) -> None:
    """A transferred marker uses annual scrobbles to choose release three."""
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "artist", release_count=3, tracks_per_release=3)
    spotify.playlists["queue"] = [tracks[1][-1]]
    write_played_release_history(tmp_path, tracks[:2])
    state = new_kids._default_state()
    state["artists"] = {
        "artist": {
            "artist_name": "Artist",
            "selected_release_ids": ["unrelated-stale-release"],
            "selected_release_identities": ["unrelated-stale-release"],
            "completed_release_ids": [],
            "current_release_id": "artist-r2",
            "prior_unliked_streak": 0,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    }
    new_kids.save_state(state, tmp_path / "state.json")

    queue_summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        year=2026,
        **isolated_paths(tmp_path),
    )
    spotify.liked_ids.add("artist-r2-t3")
    new_summary = flush(
        spotify,
        tmp_path,
        choice_reader=lambda _artist, candidates: candidates[0].spotify_id,
    )

    assert queue_summary.results == ()
    assert [track["id"] for track in spotify.playlists["new"]] == ["artist-r3-t1"]
    assert new_summary.results[0].action == "next release"
    assert new_summary.results[0].release_number == 3
    persisted = json.loads((tmp_path / "state.json").read_text())
    assert "selected_release_ids" not in persisted["artists"]["artist"]
    assert "selected_release_identities" not in persisted["artists"]["artist"]


def test_queue_2_finishes_fourth_release_without_waiting_for_new_kids(
    tmp_path: Path,
) -> None:
    """A completed Queue 2 artist is assessed immediately when New Kids is full."""
    spotify = FakeSpotify()
    for index in range(10):
        spotify.playlists["new"].append(seed_artist(spotify, f"new-{index}")[0][0])
    tracks = seed_artist(spotify, "artist", release_count=4, tracks_per_release=3)
    spotify.playlists["queue"] = [tracks[3][-1]]
    spotify.liked_ids.add("artist-r1-t1")
    spotify.saved_album_ids.update({"artist-r1", "artist-r2", "artist-r3"})
    write_played_release_history(
        tmp_path,
        tracks,
        liked_track_ids=spotify.liked_ids,
    )
    state = new_kids._default_state()
    state["artists"] = {
        "artist": {
            "artist_name": "Artist",
            "selected_release_ids": ["stale"],
            "selected_release_identities": ["stale"],
            "completed_release_ids": [],
            "current_release_id": "artist-r4",
            "prior_unliked_streak": 0,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    }
    new_kids.save_state(state, tmp_path / "state.json")

    summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        year=2026,
        **isolated_paths(tmp_path),
    )

    assert summary.results[0].action == "great discovery"
    assert spotify.playlists["queue"] == []
    assert [track["id"] for track in spotify.playlists["great"]] == ["artist-r1-t1"]
    assert [track["id"] for track in spotify.playlists["newfoundland"]] == [
        "artist-r1-t1"
    ]


def test_queue_2_resumes_after_replacement_was_added(tmp_path: Path) -> None:
    """A partial add-before-remove mutation is reconciled on restart."""
    spotify = FakeSpotify()
    for index in range(10):
        spotify.playlists["new"].append(seed_artist(spotify, f"new-{index}")[0][0])
    tracks = seed_artist(spotify, "artist")[0]
    spotify.playlists["queue"] = [tracks[0]]
    spotify.fail_playlist_delete_once = "queue"

    with pytest.raises(RuntimeError, match="interrupted"):
        new_kids.flush_queue_2(
            spotify,
            "new",
            "queue",
            "great",
            "unlucky",
            "newfoundland",
            lambda *_args: pytest.fail("release prompt was unexpected"),
            year=2026,
            **isolated_paths(tmp_path),
        )

    interrupted = json.loads((tmp_path / "state.json").read_text())
    assert interrupted["active_run"] is None
    assert interrupted["queue_2_active_run"]["status"] == "active"
    assert [track["id"] for track in spotify.playlists["queue"]] == [
        "artist-r1-t1",
        "artist-r1-t2",
    ]

    summary = new_kids.flush_queue_2(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        lambda *_args: pytest.fail("release prompt was unexpected"),
        year=2026,
        **isolated_paths(tmp_path),
    )

    assert summary.resumed is True
    assert [track["id"] for track in spotify.playlists["queue"]] == ["artist-r1-t2"]
    completed = json.loads((tmp_path / "state.json").read_text())
    assert completed["active_run"] is None
    assert completed["queue_2_active_run"] is None
