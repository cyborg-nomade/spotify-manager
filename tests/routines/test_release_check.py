import json
from collections import Counter
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.routines import blast_from_past
from spotify_manager.routines import release_check
from spotify_manager.routines import scrobble_history


def raw_artist(spotify_id: str, name: str) -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:artist:{spotify_id}",
        "name": name,
        "popularity": 50,
        "followers": {"total": 1000},
    }


def raw_release(
    spotify_id: str,
    name: str,
    artist_id: str,
    artist_name: str,
    release_date: str,
    *,
    album_type: str = "album",
    total_tracks: int = 10,
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:album:{spotify_id}",
        "name": name,
        "album_type": album_type,
        "release_date": release_date,
        "release_date_precision": "day",
        "total_tracks": total_tracks,
        "artists": [{"id": artist_id, "name": artist_name}],
    }


def raw_track(
    spotify_id: str,
    name: str,
    artist_id: str,
    artist_name: str,
    track_number: int = 1,
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": name,
        "disc_number": 1,
        "track_number": track_number,
        "artists": [{"id": artist_id, "name": artist_name}],
    }


class FakeSpotify:
    def __init__(self) -> None:
        self.artist_results: dict[str, list[dict[str, object]]] = {}
        self.catalogs: dict[str, list[dict[str, object]]] = {}
        self.release_tracks: dict[str, list[dict[str, object]]] = {}
        self.playlists: dict[str, list[dict[str, object]]] = {
            "wine": [],
            "vintage": [],
        }
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.search_calls: list[str] = []
        self.album_track_calls: Counter[str] = Counter()

    def search(self, **kwargs: object) -> dict[str, object]:
        query = str(kwargs["q"])
        self.search_calls.append(query)
        name = query.removeprefix('artist:"').removesuffix('"')
        return {"artists": {"items": self.artist_results.get(name, [])}}

    def artist_albums(self, artist_id: str, **_kwargs: object) -> dict[str, object]:
        return {
            "items": list(self.catalogs.get(artist_id, [])),
            "next": None,
        }

    def album_tracks(
        self,
        release_id: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        self.album_track_calls[release_id] += 1
        tracks = self.release_tracks.get(release_id, [])
        items = tracks[offset : offset + limit]
        next_page = offset + len(items) < len(tracks) and limit != 1
        return {"items": items, "next": "next" if next_page else None}

    def _get(
        self,
        path: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        playlist_id = path.split("/")[1]
        items = self.playlists[playlist_id]
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "next": None,
        }

    def _post(self, path: str, payload: dict[str, object]) -> None:
        self.posts.append((path, payload))
        playlist_id = path.split("/")[1]
        uris = payload["uris"]
        assert isinstance(uris, list)
        for uri in uris:
            spotify_id = str(uri).rsplit(":", 1)[-1]
            raw = next(
                track
                for tracks in self.release_tracks.values()
                for track in tracks
                if track["id"] == spotify_id
            )
            self.playlists[playlist_id].append({"item": raw})


def history_summary(*, dry_run: bool) -> scrobble_history.ScrobbleHistorySummary:
    return scrobble_history.ScrobbleHistorySummary(
        checked_at=datetime(2026, 8, 6, tzinfo=UTC),
        username="man-et-arms",
        history=(),
        export_scrobbles=300_000,
        legacy_scrobbles_added=0,
        live_scrobbles_added=2,
        dry_run=dry_run,
        persisted=not dry_run,
        backup_path=None,
    )


def patch_history_and_ranking(
    monkeypatch: pytest.MonkeyPatch,
    artists: tuple[release_check.RankedArtist, ...],
    history_dry_runs: list[bool] | None = None,
) -> None:
    def refresh(*_args: object, **kwargs: object):
        dry_run = bool(kwargs["dry_run"])
        if history_dry_runs is not None:
            history_dry_runs.append(dry_run)
        return history_summary(dry_run=dry_run)

    monkeypatch.setattr(
        release_check.scrobble_history,
        "refresh_scrobble_history",
        refresh,
    )
    monkeypatch.setattr(
        release_check,
        "rank_lastfm_artists",
        lambda _history: artists,
    )


def test_artist_progress_is_batched_into_bounded_state_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artists = tuple(
        release_check.RankedArtist(
            f"artist-{index}",
            f"Artist {index}",
            500 - index,
            index + 1,
        )
        for index in range(60)
    )
    patch_history_and_ranking(monkeypatch, artists)
    state_path = tmp_path / "state.json"
    save_calls = 0
    original_save = release_check.save_state

    def counting_save(state: dict[str, object], path: Path) -> None:
        nonlocal save_calls
        save_calls += 1
        original_save(state, path)

    monkeypatch.setattr(release_check, "save_state", counting_save)

    summary = release_check.run_release_check(
        FakeSpotify(),
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 8, 28, tzinfo=UTC),
    )

    assert summary.artists_processed == 60
    assert save_calls == 4
    assert json.loads(state_path.read_text(encoding="utf-8"))["active_run"] is None


def test_rank_lastfm_artists_normalizes_names_and_preserves_global_rank() -> None:
    history = tuple(
        blast_from_past.Scrobble("Track", "Most", "", index) for index in range(101)
    )
    history += tuple(
        blast_from_past.Scrobble(
            "Track",
            "Beyonce" if index % 2 else "Beyoncé",
            "",
            1000 + index,
        )
        for index in range(100)
    )
    history += tuple(
        blast_from_past.Scrobble("Track", "Too Small", "", 2000 + index)
        for index in range(99)
    )

    ranking = release_check.rank_lastfm_artists(history)

    assert [(artist.name, artist.scrobbles, artist.rank) for artist in ranking] == [
        ("Most", 101, 1),
        ("Beyonce", 100, 2),
    ]


def candidate(name: str, release_type: str = "Album") -> release_check.ReleaseCandidate:
    return release_check.ReleaseCandidate(
        spotify_id=name,
        uri=f"spotify:album:{name}",
        name=name,
        release_type=release_type,
        release_date="2026-08-01",
        release_date_precision="day",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )


def test_release_scope_expands_only_for_top_fifty() -> None:
    assert release_check.release_scope_reason(candidate("Live in Berlin"), 50) is None
    assert release_check.release_scope_reason(candidate("Album (Deluxe)"), 50) is None
    assert "reissue" in str(
        release_check.release_scope_reason(candidate("Album (Remastered)"), 50)
    )
    assert "live release" in str(
        release_check.release_scope_reason(candidate("Live in Berlin"), 51)
    )
    assert "deluxe" in str(
        release_check.release_scope_reason(candidate("Album (Deluxe)"), 51)
    )
    assert release_check.release_scope_reason(candidate("Plain Album"), 51) is None
    assert release_check.release_tags(candidate("Live in Berlin (Deluxe)")) == (
        "LIVE",
        "DELUXE",
    )


def test_artist_mapping_can_repeat_with_a_custom_search() -> None:
    artist = release_check.RankedArtist("artist", "Last.fm Name", 100, 51)
    spotify = FakeSpotify()
    spotify.artist_results = {
        "Last.fm Name": [],
        "Different Spotify Name": [raw_artist("correct-id", "Different Spotify Name")],
    }
    candidate_counts: list[int] = []

    def choose(
        _artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        candidate_counts.append(len(candidates))
        if not candidates:
            return f"{release_check.CHOICE_SEARCH_PREFIX}Different Spotify Name"
        return candidates[0].spotify_id

    selected = release_check.resolve_spotify_artist(
        spotify,
        artist,
        choose,
        lambda operation, _description: operation(),
    )

    assert isinstance(selected, release_check.SpotifyArtistCandidate)
    assert selected.spotify_id == "correct-id"
    assert candidate_counts == [0, 1]
    assert spotify.search_calls == [
        'artist:"Last.fm Name"',
        "Different Spotify Name",
    ]


def test_future_release_track_lists_are_cached_between_singles() -> None:
    spotify = FakeSpotify()
    future = candidate("Future Album")
    spotify.release_tracks[future.spotify_id] = [
        raw_track("shared", "Shared Song", "artist", "Artist")
    ]
    single_track = release_check.ReleaseTrack(
        spotify_id="shared",
        uri="spotify:track:shared",
        name="Shared Song",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        disc_number=1,
        track_number=1,
    )
    cache: dict[str, tuple[release_check.ReleaseTrack, ...]] = {}

    first = release_check.matching_future_release(
        spotify,
        single_track,
        (future,),
        lambda operation, _description: operation(),
        cache,
    )
    second = release_check.matching_future_release(
        spotify,
        single_track,
        (future,),
        lambda operation, _description: operation(),
        cache,
    )

    assert first == future
    assert second == future
    assert spotify.album_track_calls[future.spotify_id] == 1


def test_unavailable_future_track_list_is_treated_as_empty() -> None:
    class MissingReleaseSpotify:
        def album_tracks(self, *_args: object, **_kwargs: object) -> object:
            raise SpotifyException(404, -1, "missing")

    tracks = release_check.load_release_tracks(
        MissingReleaseSpotify(),
        candidate("Unavailable Future Album"),
        lambda operation, _description: operation(),
    )

    assert tracks == ()


def test_real_run_adds_each_tier_correctly_and_reuses_mappings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    top = release_check.RankedArtist("top", "Top Artist", 5000, 1)
    outside = release_check.RankedArtist("outside", "Outside Artist", 100, 51)
    patch_history_and_ranking(monkeypatch, (top, outside))
    spotify = FakeSpotify()
    spotify.artist_results = {
        "Top Artist": [
            raw_artist("top-wrong", "Top Artist"),
            raw_artist("top-id", "Top Artist"),
        ],
        "Outside Artist": [raw_artist("outside-id", "Outside Artist")],
    }
    spotify.catalogs = {
        "top-id": [
            raw_release("top-album", "New Album", "top-id", "Top Artist", "2026-08-05"),
            raw_release(
                "top-single",
                "New Single",
                "top-id",
                "Top Artist",
                "2026-08-04",
                album_type="single",
                total_tracks=1,
            ),
            raw_release(
                "top-live", "Live in Rome", "top-id", "Top Artist", "2026-08-03"
            ),
            raw_release(
                "top-deluxe",
                "Earlier Album (Deluxe)",
                "top-id",
                "Top Artist",
                "2026-08-02",
            ),
            raw_release(
                "top-remaster",
                "Old Album (Remastered)",
                "top-id",
                "Top Artist",
                "2026-08-01",
            ),
        ],
        "outside-id": [
            raw_release(
                "outside-album",
                "Outside Album",
                "outside-id",
                "Outside Artist",
                "2026-08-05",
            ),
            raw_release(
                "outside-single",
                "Future Song",
                "outside-id",
                "Outside Artist",
                "2026-08-04",
                album_type="single",
                total_tracks=1,
            ),
            raw_release(
                "outside-future",
                "Future Album",
                "outside-id",
                "Outside Artist",
                "2026-12-01",
            ),
        ],
    }
    spotify.release_tracks = {
        "top-album": [
            raw_track("track-top-album", "Album Opener", "top-id", "Top Artist")
        ],
        "top-single": [
            raw_track("track-top-single", "New Single", "top-id", "Top Artist")
        ],
        "top-live": [
            raw_track("track-top-live", "Live Opener", "top-id", "Top Artist")
        ],
        "top-deluxe": [
            raw_track("track-top-deluxe", "Deluxe Opener", "top-id", "Top Artist")
        ],
        "outside-album": [
            raw_track(
                "track-outside-album", "Outside Opener", "outside-id", "Outside Artist"
            )
        ],
        "outside-single": [
            raw_track(
                "track-future-song", "Future Song", "outside-id", "Outside Artist"
            )
        ],
        "outside-future": [
            raw_track("track-future-intro", "Intro", "outside-id", "Outside Artist"),
            raw_track(
                "track-future-song",
                "Future Song",
                "outside-id",
                "Outside Artist",
                2,
            ),
        ],
    }
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    choices: list[str] = []

    summary = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        artist_choice_reader=lambda artist, candidates: (
            choices.append(artist.name) or candidates[1].spotify_id
        ),
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert choices == ["Top Artist"]
    assert summary.wine_cellar_added == 6
    assert summary.new_vintage_added == 4
    remaster = next(
        result for result in summary.results if result.release_id == "top-remaster"
    )
    assert remaster.reason == "non-deluxe reissue or remaster"
    linked = next(
        result for result in summary.results if result.release_id == "outside-single"
    )
    assert linked.linked_future_release == "Future Album"
    assert linked.wine_cellar_action == "added"
    assert linked.new_vintage_action == "not applicable"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["artist_mappings"]["top"]["spotify_id"] == "top-id"
    assert state["last_checked_through"] == "2026-08-06"
    assert state["active_run"] is None
    assert log_path.read_text(encoding="utf-8").count("release_checked") == 7

    posts_after_first_run = len(spotify.posts)
    search_calls_after_first_run = len(spotify.search_calls)
    second = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        artist_choice_reader=lambda *_args: pytest.fail("mapping should be reused"),
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert second.results == ()
    assert len(spotify.posts) == posts_after_first_run
    assert len(spotify.search_calls) == search_calls_after_first_run


def test_release_prompt_can_permanently_skip_an_eligible_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("artist", "Artist", 500, 10)
    patch_history_and_ranking(monkeypatch, (artist,))
    spotify = FakeSpotify()
    spotify.artist_results = {"Artist": [raw_artist("artist-id", "Artist")]}
    spotify.catalogs = {
        "artist-id": [
            raw_release(
                "deluxe",
                "New Album (Deluxe)",
                "artist-id",
                "Artist",
                "2026-08-05",
            )
        ]
    }
    spotify.release_tracks = {
        "deluxe": [raw_track("opener", "Opener", "artist-id", "Artist")]
    }
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    prompts: list[tuple[str, ...]] = []

    def choose_release(
        _artist: release_check.RankedArtist,
        _release: release_check.ReleaseCandidate,
        _track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        _unattached: bool,
    ) -> str:
        prompts.append(destinations)
        return release_check.CHOICE_SKIP

    summary = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        release_choice_reader=choose_release,
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert prompts == [("Wine Cellar", "New Vintage")]
    assert spotify.posts == []
    assert summary.results[0].reason == "skipped by user"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["processed_releases"]["deluxe"]["reason"] == "skipped by user"


def test_unattached_single_can_be_added_to_wine_cellar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("later", "Later Artist", 100, 51)
    patch_history_and_ranking(monkeypatch, (artist,))
    spotify = FakeSpotify()
    spotify.artist_results = {"Later Artist": [raw_artist("later-id", "Later Artist")]}
    spotify.catalogs = {
        "later-id": [
            raw_release(
                "standalone-single",
                "Standalone Song",
                "later-id",
                "Later Artist",
                "2026-08-05",
                album_type="single",
                total_tracks=1,
            )
        ]
    }
    spotify.release_tracks = {
        "standalone-single": [
            raw_track("standalone-track", "Standalone Song", "later-id", "Later Artist")
        ]
    }
    state_path = tmp_path / "state.json"
    prompts: list[tuple[tuple[str, ...], bool]] = []

    summary = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        release_choice_reader=(
            lambda _artist, _release, _track, destinations, unattached: (
                prompts.append((destinations, unattached)) or release_check.CHOICE_ADD
            )
        ),
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert prompts == [(("Wine Cellar",), True)]
    assert summary.results[0].wine_cellar_action == "added"
    assert summary.results[0].new_vintage_action == "not applicable"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "standalone-single" in state["processed_releases"]
    assert state["pending_singles"] == {}


def test_permanent_artist_skip_persists_during_dry_run_and_avoids_search(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("missing", "Missing Artist", 100, 51)
    patch_history_and_ranking(monkeypatch, (artist,))
    spotify = FakeSpotify()
    state_path = tmp_path / "state.json"

    first = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        artist_choice_reader=lambda _artist, _candidates: (
            release_check.CHOICE_SKIP_ARTIST
        ),
        dry_run=True,
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert first.artists_processed == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["skipped_artists"]["missing"]["artist"] == "Missing Artist"
    search_calls = list(spotify.search_calls)

    second = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        artist_choice_reader=lambda *_args: pytest.fail(
            "permanently skipped artist should not be mapped again"
        ),
        dry_run=True,
        state_path=state_path,
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert second.artists_processed == 1
    assert spotify.search_calls == search_calls


def test_unconfirmed_single_is_reconsidered_when_future_album_appears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("later", "Later Artist", 100, 51)
    patch_history_and_ranking(monkeypatch, (artist,))
    spotify = FakeSpotify()
    spotify.artist_results = {"Later Artist": [raw_artist("later-id", "Later Artist")]}
    single = raw_release(
        "later-single",
        "Announced Later",
        "later-id",
        "Later Artist",
        "2026-08-05",
        album_type="single",
        total_tracks=1,
    )
    spotify.catalogs = {"later-id": [single]}
    spotify.release_tracks = {
        "later-single": [
            raw_track("later-track", "Announced Later", "later-id", "Later Artist")
        ]
    }
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"

    first = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert first.results[0].reason == "single kept pending for a future album or EP"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "later-single" in state["pending_singles"]
    assert "later-single" not in state["processed_releases"]

    future = raw_release(
        "later-future",
        "The Announced Album",
        "later-id",
        "Later Artist",
        "2026-12-01",
    )
    spotify.catalogs["later-id"] = [future, single]
    spotify.release_tracks["later-future"] = [
        raw_track("later-track", "Announced Later", "later-id", "Later Artist")
    ]

    second = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert len(second.results) == 1
    assert second.results[0].linked_future_release == "The Announced Album"
    assert second.results[0].wine_cellar_action == "added"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "later-single" not in state["pending_singles"]
    assert "later-single" in state["processed_releases"]


def test_pending_single_closes_when_its_album_is_already_released(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("later", "Later Artist", 100, 51)
    patch_history_and_ranking(monkeypatch, (artist,))
    spotify = FakeSpotify()
    spotify.artist_results = {"Later Artist": [raw_artist("later-id", "Later Artist")]}
    single = raw_release(
        "later-single",
        "Album Song",
        "later-id",
        "Later Artist",
        "2026-08-05",
        album_type="single",
        total_tracks=1,
    )
    spotify.catalogs = {"later-id": [single]}
    spotify.release_tracks = {
        "later-single": [
            raw_track("album-song", "Album Song", "later-id", "Later Artist")
        ]
    }
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"

    release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    album = raw_release(
        "released-album",
        "Released Album",
        "later-id",
        "Later Artist",
        "2026-08-07",
    )
    spotify.catalogs["later-id"] = [album, single]
    spotify.release_tracks["released-album"] = [
        raw_track("album-song", "Album Song", "later-id", "Later Artist")
    ]

    summary = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    pending_result = next(
        result for result in summary.results if result.release_id == "later-single"
    )
    assert pending_result.reason == "containing album or EP has already been released"
    assert pending_result.wine_cellar_action == "not applicable"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "later-single" not in state["pending_singles"]
    assert "later-single" in state["processed_releases"]


def test_dry_run_persists_only_history_and_artist_mappings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artist = release_check.RankedArtist("dry", "Dry Artist", 200, 1)
    history_dry_runs: list[bool] = []
    patch_history_and_ranking(monkeypatch, (artist,), history_dry_runs)
    spotify = FakeSpotify()
    spotify.artist_results = {"Dry Artist": [raw_artist("dry-id", "Dry Artist")]}
    spotify.catalogs = {
        "dry-id": [
            raw_release("dry-album", "Dry Album", "dry-id", "Dry Artist", "2026-08-05")
        ]
    }
    spotify.release_tracks = {
        "dry-album": [raw_track("dry-track", "Dry Opener", "dry-id", "Dry Artist")]
    }
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"

    summary = release_check.run_release_check(
        spotify,
        object(),
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="man-et-arms",
        dry_run=True,
        state_path=state_path,
        log_path=log_path,
        now=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert summary.results[0].wine_cellar_action == "would add"
    assert summary.results[0].new_vintage_action == "would add"
    assert spotify.posts == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["artist_mappings"]["dry"]["spotify_id"] == "dry-id"
    assert state["active_run"] is None
    assert state["processed_releases"] == {}
    assert state["last_checked_through"] is None
    assert history_dry_runs == [False]
    assert not log_path.exists()


def test_state_save_fingerprints_and_restore_backup(tmp_path: Path) -> None:
    state_path = tmp_path / "release-state.json"
    backup_dir = tmp_path / "backups"
    original = release_check._default_state()
    release_check.save_state(original, state_path)
    saved_original = state_path.read_bytes()
    loaded = release_check.load_state(state_path)

    assert release_check.state_updated_at(loaded) is not None
    original_fingerprint = release_check.state_fingerprint(loaded)

    replacement = release_check.validate_state(loaded)
    replacement["artist_mappings"]["artist"] = {"spotify_id": "spotify-artist"}
    backup_path = release_check.restore_state(
        replacement,
        state_path,
        backup_dir,
    )
    restored = release_check.load_state(state_path)

    assert backup_path is not None
    assert backup_path.read_bytes() == saved_original
    assert restored["artist_mappings"]["artist"]["spotify_id"] == "spotify-artist"
    assert release_check.state_fingerprint(restored) != original_fingerprint
