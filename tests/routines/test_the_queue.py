"""Tests for The Queue's artist recommendation and flush routines."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import the_queue


def raw_release(
    release_id: str,
    artist_id: str,
    *,
    artist_name: str = "Artist",
    name: str | None = None,
    total_tracks: int = 3,
    popularity: int = 60,
) -> dict[str, object]:
    """Build one Spotify album used by Queue tests."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name or f"Release {release_id}",
        "album_type": "album",
        "release_date": "2020-01-01",
        "total_tracks": total_tracks,
        "popularity": popularity,
        "artists": [{"id": artist_id, "name": artist_name}],
    }


def raw_track(
    track_id: str,
    artist_id: str,
    release: dict[str, object],
    *,
    artist_name: str = "Artist",
    name: str | None = None,
    track_number: int = 1,
    popularity: int = 70,
) -> dict[str, object]:
    """Build one primary-artist Spotify track."""
    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "name": name or f"Track {track_id}",
        "disc_number": 1,
        "track_number": track_number,
        "popularity": popularity,
        "artists": [{"id": artist_id, "name": artist_name}],
        "album": release,
    }


class FakeSpotify:
    """Mutable Spotify simulation covering both Queue commands."""

    def __init__(self) -> None:
        self.playlists: dict[str, list[dict[str, object]]] = {
            "queue": [],
            "queue2": [],
            "new-kids": [],
            "queue3": [],
            "unlucky": [],
        }
        self.artist_releases: dict[str, list[dict[str, object]]] = {}
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.top_tracks: dict[str, list[dict[str, object]]] = {}
        self.artist_search: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.followed_ids: set[str] = set()
        self.saved_album_ids: set[str] = set()
        self.mutations: list[tuple[str, str, str]] = []
        self.fail_delete_once = False

    def all_tracks(self) -> list[dict[str, object]]:
        return [
            track
            for tracks in [*self.release_tracks.values(), *self.playlists.values()]
            for track in tracks
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
        uris = payload["uris"]
        assert isinstance(uris, list)
        for uri in uris:
            track = next(track for track in self.all_tracks() if track["uri"] == uri)
            if all(existing["uri"] != uri for existing in self.playlists[playlist_id]):
                self.playlists[playlist_id].append(track)
                self.mutations.append(("add", playlist_id, str(track["id"])))
        return {}

    def _delete(
        self,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        uris: str | None = None,
    ):
        if path == "me/library":
            assert uris is not None
            artist_ids = [uri.rsplit(":", 1)[-1] for uri in uris.split(",")]
            self.user_unfollow_artists(artist_ids)
            return {}
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("interrupted deletion")
        playlist_id = path.split("/")[1]
        assert payload is not None
        items = payload["items"]
        assert isinstance(items, list)
        uris = {str(item["uri"]) for item in items}
        removed = [
            track for track in self.playlists[playlist_id] if track["uri"] in uris
        ]
        self.playlists[playlist_id] = [
            track for track in self.playlists[playlist_id] if track["uri"] not in uris
        ]
        self.mutations.extend(
            ("remove", playlist_id, str(track["id"])) for track in removed
        )
        return {}

    def artist_top_tracks(self, artist_id: str):
        return {"tracks": self.top_tracks.get(artist_id, [])}

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
        by_id = {
            str(release["id"]): release
            for releases in self.artist_releases.values()
            for release in releases
        }
        return {"albums": [by_id[album_id] for album_id in album_ids]}

    def album_tracks(self, album_id: str, *, limit: int, offset: int):
        tracks = self.release_tracks[album_id]
        page = tracks[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(tracks) else None,
        }

    def tracks(self, track_ids: list[str]):
        by_id = {str(track["id"]): track for track in self.all_tracks()}
        return {"tracks": [by_id[track_id] for track_id in track_ids]}

    def current_user_saved_tracks_contains(self, track_ids: list[str]):
        return [track_id in self.liked_ids for track_id in track_ids]

    def current_user_saved_albums_contains(self, album_ids: list[str]):
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def current_user_following_artists(self, artist_ids: list[str]):
        return [artist_id in self.followed_ids for artist_id in artist_ids]

    def user_follow_artists(self, artist_ids: list[str]):
        self.followed_ids.update(artist_ids)
        self.mutations.extend(
            ("follow", "library", artist_id) for artist_id in artist_ids
        )

    def user_unfollow_artists(self, artist_ids: list[str]):
        self.followed_ids.difference_update(artist_ids)
        self.mutations.extend(
            ("unfollow", "library", artist_id) for artist_id in artist_ids
        )

    def search(self, *, q: str, limit: int, offset: int, **kwargs: str):
        assert kwargs["type"] == "artist"
        assert limit == 10
        assert offset == 0
        return {"artists": {"items": self.artist_search.get(q, [])}}


class FakeLastFm:
    """Last.fm neighbor source for artist recommendation tests."""

    username = "listener"

    def __init__(self) -> None:
        self.similar: dict[str, tuple[LastFmSimilarArtist, ...]] = {}
        self.calls: list[str] = []

    def similar_artists(
        self,
        artist: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarArtist, ...]:
        assert limit == 50
        self.calls.append(artist)
        return self.similar.get(artist, ())

    def similar_tracks(self, artist: str, track: str, *, limit: int = 50):
        return ()

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ):
        return ()


def queue_playlists() -> the_queue.QueuePlaylists:
    return the_queue.QueuePlaylists(
        queue="queue",
        queue_2="queue2",
        new_kids="new-kids",
        queue_3="queue3",
        unlucky_ones="unlucky",
    )


def seed_artist(
    spotify: FakeSpotify,
    artist_id: str,
    *,
    track_count: int = 3,
) -> list[dict[str, object]]:
    """Create one album and ordered top tracks for an artist."""
    name = f"Artist {artist_id}"
    release = raw_release(
        f"{artist_id}-album",
        artist_id,
        artist_name=name,
        total_tracks=track_count,
    )
    tracks = [
        raw_track(
            f"{artist_id}-t{index}",
            artist_id,
            release,
            artist_name=name,
            track_number=index,
            popularity=100 - index,
        )
        for index in range(1, track_count + 1)
    ]
    spotify.artist_releases[artist_id] = [release]
    spotify.release_tracks[str(release["id"])] = tracks
    spotify.top_tracks[artist_id] = tracks[:10]
    return tracks


def isolated_paths(tmp_path: Path) -> dict[str, Path]:
    artists_path = tmp_path / "artists.json"
    artists_path.write_text("[]\n")
    return {
        "state_path": tmp_path / "state.json",
        "log_path": tmp_path / "log.jsonl",
        "artists_path": artists_path,
    }


def scrobble(artist: str, timestamp_ms: int) -> blast_from_past.Scrobble:
    return blast_from_past.Scrobble(
        track="Track",
        artist=artist,
        album="Album",
        timestamp_ms=timestamp_ms,
    )


def test_queue_playlists_require_every_configuration_value() -> None:
    with pytest.raises(the_queue.QueueConfigError, match="THE_QUEUE_PLAYLIST"):
        the_queue.QueuePlaylists.from_references(
            None,
            "queue2",
            "new-kids",
            "queue3",
            "unlucky",
        )


@pytest.mark.parametrize(
    "contents",
    [
        "not json",
        json.dumps({"version": 99, "artist_mappings": {}, "active_flush": None}),
        json.dumps({"version": 1, "artist_mappings": [], "active_flush": None}),
        json.dumps({"version": 1, "artist_mappings": {}, "active_flush": []}),
    ],
)
def test_queue_state_rejects_corrupt_or_incompatible_data(
    tmp_path: Path,
    contents: str,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(contents)

    with pytest.raises(the_queue.QueueStateError, match="Queue state is invalid"):
        the_queue.load_state(state_path)


def test_queue_storage_write_failures_are_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_write(*_args: object, **_kwargs: object) -> int:
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(the_queue.QueueStateError, match="Could not save Queue state"):
        the_queue.save_state(
            {"version": 1, "artist_mappings": {}, "active_flush": None},
            tmp_path / "state.json",
        )
    with pytest.raises(the_queue.QueueStateError, match="Could not save Queue cache"):
        the_queue._save_cache(
            {"version": 1, "entries": {}},
            tmp_path / "cache.json",
        )


def test_queue_log_write_failure_is_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*_args: object, **_kwargs: object) -> object:
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(the_queue.QueueStateError, match="Could not write Queue log"):
        the_queue.append_event(tmp_path / "log.jsonl", "test")


def test_empty_history_and_invalid_seed_counts_are_explicit() -> None:
    assert the_queue.aggregate_artist_history(()) == ()
    assert the_queue.aggregate_artist_history((scrobble("!!!", 1),)) == ()
    with pytest.raises(the_queue.QueueConfigError, match="at least 1"):
        the_queue.select_seed_artists((), seed_count=0)
    with pytest.raises(the_queue.QueueStateError, match="Only 0 seed artists"):
        the_queue.select_seed_artists((), seed_count=1)


def test_artist_history_and_weekly_seeds_are_diverse() -> None:
    history = the_queue.aggregate_artist_history(
        [
            scrobble("Recent", 400 * 86_400_000),
            scrobble("Annual", 200 * 86_400_000),
            scrobble("Overall", 1),
        ]
    )

    seeds = the_queue.select_seed_artists(
        history,
        seed_count=3,
        week_start=date(2026, 8, 7),
    )

    assert {seed.artist for seed in seeds} == {"Recent", "Annual", "Overall"}
    assert {seed.source for seed in seeds} == {"recent", "annual", "overall"}


def test_seed_selection_falls_back_to_older_history() -> None:
    history = tuple(
        the_queue.ArtistHistory(
            artist=f"Archive {index}",
            key=f"archive{index}",
            play_count=10 - index,
            recent_play_count=0,
            annual_play_count=0,
            last_played_ms=index,
        )
        for index in range(4)
    )

    seeds = the_queue.select_seed_artists(
        history,
        seed_count=4,
        week_start=date(2026, 8, 7),
    )

    assert len(seeds) == 4
    assert {seed.key for seed in seeds} == {artist.key for artist in history}
    assert all(seed.source == "overall" for seed in seeds)


def test_recommendations_exclude_heard_and_previous_artists_and_cache(
    tmp_path: Path,
) -> None:
    lastfm = FakeLastFm()
    lastfm.similar["Seed"] = (
        LastFmSimilarArtist("Heard", 1.0),
        LastFmSimilarArtist("Previous", 0.9),
        LastFmSimilarArtist("Fresh", 0.8),
    )
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "event": "artist_added",
                "lastfm_artist_key": the_queue.canonical_artist_key("Previous"),
            }
        )
        + "\n"
    )
    seed = the_queue.ArtistSeed(
        "Seed",
        the_queue.canonical_artist_key("Seed"),
        "overall",
        10,
        10,
        1.0,
        1.0,
    )
    kwargs = {
        "cache_path": tmp_path / "cache.json",
        "log_path": log_path,
        "week_start": date(2026, 8, 7),
        "now": datetime(2026, 8, 11, tzinfo=UTC),
    }

    progress: list[str] = []
    first = the_queue.gather_artist_recommendations(
        lastfm,
        (seed,),
        {the_queue.canonical_artist_key("Heard")},
        progress_callback=lambda _done, _total, label: progress.append(label),
        **kwargs,
    )
    second = the_queue.gather_artist_recommendations(
        lastfm,
        (seed,),
        {the_queue.canonical_artist_key("Heard")},
        **kwargs,
    )

    assert [candidate.artist for candidate in first] == ["Fresh"]
    assert second == first
    assert lastfm.calls == ["Seed"]
    assert progress == ["Last.fm neighbors: Seed"]


def test_recommendation_cache_and_log_reject_corruption(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not json")
    with pytest.raises(the_queue.QueueStateError, match="cache is invalid"):
        the_queue._load_cache(cache_path)

    cache_path.write_text(json.dumps({"version": 2, "entries": {}}))
    with pytest.raises(the_queue.QueueStateError, match="cache is invalid"):
        the_queue._load_cache(cache_path)

    log_path = tmp_path / "log.jsonl"
    log_path.write_text("\nnot json\n")
    with pytest.raises(the_queue.QueueStateError, match="Queue log is invalid"):
        the_queue.previously_added_artist_keys(log_path)


def test_cached_similar_artists_validate_shape_and_week() -> None:
    week = date(2026, 8, 7)
    assert the_queue._cached_similar_artists(None, week) is None
    assert (
        the_queue._cached_similar_artists(
            {"fetched_at": "2026-08-01T00:00:00+00:00", "artists": []},
            week,
        )
        is None
    )
    assert (
        the_queue._cached_similar_artists(
            {"fetched_at": "2026-08-11T00:00:00", "artists": "invalid"},
            week,
        )
        is None
    )
    assert the_queue._cached_similar_artists({}, week) is None
    assert the_queue._cached_similar_artists(
        {
            "fetched_at": "2026-08-11T00:00:00",
            "artists": [{"artist": "Neighbor", "match": 0.75}],
        },
        week,
    ) == (LastFmSimilarArtist("Neighbor", 0.75),)


def test_queue_mapping_likes_and_follow_persistence_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert the_queue._mapped_artist({"spotify_id": "incomplete"}) is None
    spotify = FakeSpotify()
    assert (
        the_queue._liked_statuses(
            spotify,
            (),
            lambda operation, _label: operation(),
        )
        == {}
    )
    track = the_queue.new_kids.CatalogTrack(
        "track",
        "spotify:track:track",
        "Track",
        1,
        1,
        "artist",
        "Artist",
    )
    with pytest.raises(the_queue.QueueSpotifyError, match="Liked Songs statuses"):
        the_queue._liked_statuses(spotify, (track,), lambda _operation, _label: [])

    monkeypatch.setattr(
        the_queue,
        "record_followed_artist",
        lambda _artist: SimpleNamespace(
            total_artists_updated=True,
            stats_history_updated=True,
        ),
    )
    messages: list[str] = []
    the_queue._persist_followed_artist(
        the_queue.release_check.SpotifyArtistCandidate(
            "artist",
            "Artist",
            "spotify:artist:artist",
            50,
            100,
            1,
            True,
        ),
        messages.append,
    )
    assert messages == [
        "Recorded artist in artists_total.json: Artist",
        "Updated stats_history.json.",
    ]


@pytest.mark.parametrize(
    "loader, raw",
    [
        (the_queue._playlist_track_from_record, None),
        (the_queue._playlist_track_from_record, {"release": {}}),
        (the_queue._catalog_track_from_record, []),
        (the_queue._catalog_track_from_record, {}),
    ],
)
def test_queue_resumed_records_reject_invalid_shapes(
    loader: object,
    raw: object,
) -> None:
    with pytest.raises(the_queue.QueueStateError):
        loader(raw)  # type: ignore[operator]


def test_queue_catalog_record_accepts_an_empty_target() -> None:
    assert the_queue._catalog_track_from_record(None) is None


def test_flush_skips_liked_top_tracks_and_limits_unique_artists(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    for index in range(1, 12):
        tracks = seed_artist(spotify, f"a{index}")
        spotify.playlists["queue"].append(tracks[0])
        spotify.liked_ids.add(str(tracks[1]["id"]))
    spotify.playlists["queue"].insert(1, spotify.playlists["queue"][0])

    summary = the_queue.flush_queue(
        spotify,
        queue_playlists(),
        **isolated_paths(tmp_path),
    )

    assert summary.total == 10
    assert summary.processed == 10
    assert all(result.action == "advance" for result in summary.results)
    assert all(
        result.target_track.endswith("t3")
        for result in summary.results
        if result.target_track
    )
    remaining_ids = [str(track["id"]) for track in spotify.playlists["queue"]]
    assert "a11-t1" in remaining_ids
    assert "a1-t1" not in remaining_ids
    assert "a1-t3" in remaining_ids


def test_flush_promotes_immediately_at_six_live_likes(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "promote", track_count=7)
    spotify.playlists["queue"] = [tracks[0]]
    spotify.liked_ids.update(str(track["id"]) for track in tracks[:6])

    summary = the_queue.flush_queue(
        spotify,
        queue_playlists(),
        **isolated_paths(tmp_path),
    )

    result = summary.results[0]
    assert result.action == "promote"
    assert result.total_liked_tracks == 6
    assert [track["id"] for track in spotify.playlists["queue2"]] == ["promote-t1"]
    assert spotify.playlists["queue"] == []


def test_flush_promotes_five_of_top_ten_at_endpoint(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "endpoint", track_count=6)
    spotify.playlists["queue"] = [tracks[-1]]
    spotify.liked_ids.update(str(track["id"]) for track in tracks[:5])

    summary = the_queue.flush_queue(
        spotify,
        queue_playlists(),
        **isolated_paths(tmp_path),
    )

    assert summary.results[0].action == "promote"
    assert summary.results[0].top_liked_tracks == 5


def test_flush_rejects_to_unlucky_and_unfollows(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "reject", track_count=3)
    spotify.playlists["queue"] = [tracks[-1]]
    spotify.liked_ids.add(str(tracks[0]["id"]))
    spotify.followed_ids.add("reject")

    summary = the_queue.flush_queue(
        spotify,
        queue_playlists(),
        **isolated_paths(tmp_path),
    )

    assert summary.results[0].action == "unlucky"
    assert [track["id"] for track in spotify.playlists["unlucky"]] == ["reject-t1"]
    assert "reject" not in spotify.followed_ids
    assert spotify.playlists["queue"] == []


def test_flush_resumes_after_target_was_added(tmp_path: Path) -> None:
    spotify = FakeSpotify()
    tracks = seed_artist(spotify, "resume")
    spotify.playlists["queue"] = [tracks[0]]
    paths = isolated_paths(tmp_path)
    spotify.fail_delete_once = True

    with pytest.raises(RuntimeError, match="interrupted"):
        the_queue.flush_queue(spotify, queue_playlists(), **paths)

    assert [track["id"] for track in spotify.playlists["queue"]] == [
        "resume-t1",
        "resume-t2",
    ]
    summary = the_queue.flush_queue(spotify, queue_playlists(), **paths)

    assert summary.resumed is True
    assert [track["id"] for track in spotify.playlists["queue"]] == ["resume-t2"]
    assert (
        sum(mutation == ("add", "queue", "resume-t2") for mutation in spotify.mutations)
        == 1
    )


def test_fill_maps_follows_and_adds_first_unliked_top_track(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify()
    seed_artist(spotify, "fresh")
    spotify.liked_ids.add("fresh-t1")
    spotify.artist_search['artist:"Fresh Artist"'] = [
        {
            "id": "fresh",
            "uri": "spotify:artist:fresh",
            "name": "Fresh Artist",
            "popularity": 50,
            "followers": {"total": 100},
        }
    ]
    lastfm = FakeLastFm()
    history = [scrobble(f"Seed {index}", 1_000_000 + index) for index in range(1, 4)]
    lastfm.similar = {
        f"Seed {index}": (LastFmSimilarArtist("Fresh Artist", 0.9),)
        for index in range(1, 4)
    }
    monkeypatch.setattr(
        the_queue.found_art,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: (history, 0),
    )
    monkeypatch.setattr(the_queue, "_persist_followed_artist", lambda *_args: None)

    summary = the_queue.fill_queue_from_lastfm(
        spotify,
        lastfm,
        queue_playlists(),
        None,
        count=1,
        seed_count=3,
        state_path=tmp_path / "state.json",
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        export_path=tmp_path / "history.json",
        recent_path=tmp_path / "recent.jsonl",
        now=datetime(2026, 8, 11, tzinfo=UTC),
    )

    assert summary.selected == 1
    assert summary.results[-1].track is not None
    assert summary.results[-1].track.spotify_id == "fresh-t2"
    assert [track["id"] for track in spotify.playlists["queue"]] == ["fresh-t2"]
    assert "fresh" in spotify.followed_ids
    state = json.loads((tmp_path / "state.json").read_text())
    assert (
        state["artist_mappings"][the_queue.canonical_artist_key("Fresh Artist")][
            "spotify_id"
        ]
        == "fresh"
    )


@pytest.mark.parametrize(
    ("count", "maximum", "message"),
    [
        (1, 10, "either count"),
        (0, None, "Count must"),
        (None, 0, "Maximum playlist length"),
    ],
)
def test_fill_validates_requested_size(
    count: int | None,
    maximum: int | None,
    message: str,
) -> None:
    with pytest.raises(the_queue.QueueConfigError, match=message):
        the_queue.fill_queue_from_lastfm(
            FakeSpotify(),
            FakeLastFm(),
            queue_playlists(),
            None,
            count=count,
            max_playlist_length=maximum,
        )


def test_fill_at_maximum_playlist_length_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify()
    spotify.playlists["queue"] = [seed_artist(spotify, "existing")[0]]
    history = [scrobble("Seed", 1_000)]
    monkeypatch.setattr(
        the_queue.found_art,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: (history, 2),
    )

    summary = the_queue.fill_queue_from_lastfm(
        spotify,
        FakeLastFm(),
        queue_playlists(),
        None,
        count=None,
        max_playlist_length=1,
        export_path=tmp_path / "history.json",
        recent_path=tmp_path / "recent.jsonl",
    )

    assert summary.requested_count == 0
    assert summary.live_scrobbles_added == 2
    assert summary.results == ()


@pytest.mark.parametrize(
    ("choice", "expected_action", "paused"),
    [
        (the_queue.CHOICE_SKIP, "skipped", False),
        (the_queue.CHOICE_QUIT, None, True),
        (None, "no Spotify match", False),
    ],
)
def test_fill_handles_mapping_skip_quit_and_no_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    choice: str | None,
    expected_action: str | None,
    paused: bool,
) -> None:
    spotify = FakeSpotify()
    if choice is not None:
        spotify.artist_search['artist:"Fresh Artist"'] = [
            {
                "id": "different",
                "uri": "spotify:artist:different",
                "name": "Different Artist",
                "popularity": 10,
                "followers": {"total": 2},
            }
        ]
    history = [scrobble("Seed", 1_000)]
    recommendation = the_queue.ArtistRecommendation(
        artist="Fresh Artist",
        key=the_queue.canonical_artist_key("Fresh Artist"),
        score=1.0,
        best_match=1.0,
        supporting_seeds=("Seed",),
        base_rank=1,
    )
    monkeypatch.setattr(
        the_queue.found_art,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: (history, 0),
    )
    monkeypatch.setattr(
        the_queue,
        "gather_artist_recommendations",
        lambda *_args, **_kwargs: (recommendation,),
    )
    reader = None if choice is None else lambda *_args: choice

    summary = the_queue.fill_queue_from_lastfm(
        spotify,
        FakeLastFm(),
        queue_playlists(),
        reader,
        count=1,
        seed_count=1,
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "log.jsonl",
    )

    assert summary.paused is paused
    assert [result.action for result in summary.results] == (
        [] if expected_action is None else [expected_action]
    )


def test_fill_skips_represented_and_fully_liked_artists_before_dry_run_addition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify()
    represented_tracks = seed_artist(spotify, "represented")
    liked_tracks = seed_artist(spotify, "liked")
    candidate_tracks = seed_artist(spotify, "candidate")
    seed_artist(spotify, "unused")
    spotify.playlists["queue2"] = [represented_tracks[0]]
    spotify.liked_ids.update(str(track["id"]) for track in liked_tracks)
    spotify.followed_ids.add("candidate")
    history = [scrobble("Seed", 1_000)]
    recommendations = tuple(
        the_queue.ArtistRecommendation(
            artist=f"Artist {artist_id}",
            key=the_queue.canonical_artist_key(f"Artist {artist_id}"),
            score=1.0,
            best_match=1.0,
            supporting_seeds=("Seed",),
            base_rank=index,
        )
        for index, artist_id in enumerate(
            ("represented", "liked", "candidate", "unused"), start=1
        )
    )
    mappings = {
        recommendation.key: {
            "spotify_id": artist_id,
            "name": recommendation.artist,
            "uri": f"spotify:artist:{artist_id}",
            "popularity": 50,
            "followers": 100,
            "search_rank": 1,
            "exact_name": True,
        }
        for recommendation, artist_id in zip(
            recommendations,
            ("represented", "liked", "candidate", "unused"),
            strict=True,
        )
    }
    state_path = tmp_path / "state.json"
    the_queue.save_state(
        {"version": 1, "artist_mappings": mappings, "active_flush": None},
        state_path,
    )
    monkeypatch.setattr(
        the_queue.found_art,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: (history, 0),
    )
    monkeypatch.setattr(
        the_queue,
        "gather_artist_recommendations",
        lambda *_args, **_kwargs: recommendations,
    )
    progress: list[str] = []

    summary = the_queue.fill_queue_from_lastfm(
        spotify,
        FakeLastFm(),
        queue_playlists(),
        None,
        count=1,
        seed_count=1,
        dry_run=True,
        progress_callback=lambda _done, _total, label: progress.append(label),
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
    )

    assert [result.action for result in summary.results] == [
        "already represented",
        "no unliked top track",
        "would add",
    ]
    assert summary.results[-1].track is not None
    assert summary.results[-1].track.spotify_id == candidate_tracks[0]["id"]
    assert progress[-1] == "Resolving Artist candidate"
    assert spotify.playlists["queue"] == []


def test_playlist_references_accept_share_links() -> None:
    playlists = the_queue.QueuePlaylists.from_references(
        "https://open.spotify.com/playlist/4BORocfcq3t2PmXd7tLcs1?si=x",
        "spotify:playlist:1zgC1g8eJCGRSDEGD5qw2D",
        "4j6jW1MG4AIH2FKkrRTxCZ",
        "7oS9nZjXFTKxwsvxRDiBwh",
        "5SKyWmINQl4OpqLQzQe2uJ",
    )

    assert playlists.queue == "4BORocfcq3t2PmXd7tLcs1"
