"""Tests for Last.fm-style Found Art recommendations."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.client.lastfm import LastFmSimilarTrack
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art


class FakeLastFm:
    """Deterministic Last.fm source for history and similar tracks."""

    def __init__(self) -> None:
        self.recent: tuple[LastFmRecentTrack, ...] = ()
        self.similar: dict[tuple[str, str], tuple[LastFmSimilarTrack, ...]] = {}
        self.similar_calls: list[tuple[str, str, int]] = []

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        assert from_timestamp <= to_timestamp
        assert limit == 200
        return self.recent

    def similar_tracks(
        self,
        artist: str,
        track: str,
        *,
        limit: int = 50,
    ) -> tuple[LastFmSimilarTrack, ...]:
        self.similar_calls.append((artist, track, limit))
        return self.similar.get((artist, track), ())


def spotify_track(
    spotify_id: str,
    track: str,
    artist: str,
    album: str = "Album",
) -> dict[str, object]:
    """Return a Spotify-shaped search result."""
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": track,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "popularity": 50,
    }


class FakeSpotify:
    """Spotify stand-in for Found Art resolution."""

    def __init__(self) -> None:
        self.search_results: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.posts: list[tuple[str, dict[str, object]]] = []

    def search(
        self,
        q: str,
        limit: int,
        offset: int,
        **kwargs: str,
    ) -> dict[str, object]:
        assert limit == blast_from_past.SPOTIFY_SEARCH_LIMIT
        assert offset == 0
        assert kwargs["type"] == "track"
        return {"tracks": {"items": self.search_results.get(q, [])}}

    def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        return [spotify_id in self.liked_ids for spotify_id in ids]

    def _post(self, path: str, payload: dict[str, object]) -> None:
        self.posts.append((path, payload))


def seed(
    artist: str,
    track: str,
    source: str = "recent",
) -> found_art.FoundArtSeed:
    """Return one compact recommendation seed."""
    return found_art.FoundArtSeed(
        artist=artist,
        track=track,
        key=found_art.canonical_track_key(artist, track),
        source=source,  # type: ignore[arg-type]
        play_count=10,
        source_play_count=5,
        weight=1.0,
    )


def candidate(artist: str, track: str, score: float) -> found_art.FoundArtCandidate:
    """Return one compact ranked candidate."""
    return found_art.FoundArtCandidate(
        artist=artist,
        track=track,
        key=found_art.canonical_track_key(artist, track),
        score=score,
        best_match=score,
        supporting_seeds=("Seed Artist - Seed Track",),
    )


def test_canonical_key_treats_edition_suffixes_as_the_same_track() -> None:
    plain = found_art.canonical_track_key("Beyoncé", "Song")
    remaster = found_art.canonical_track_key(
        "Beyonce",
        "Song - 2011 Remastered",
    )
    live = found_art.canonical_track_key("Beyonce", "Song (Live)")

    assert plain == remaster == live


def test_listening_weeks_start_on_friday_in_berlin() -> None:
    thursday = datetime(2026, 7, 23, 21, 30, tzinfo=UTC)
    friday_in_berlin = datetime(2026, 7, 23, 22, 30, tzinfo=UTC)

    assert found_art.listening_week_start(thursday) == date(2026, 7, 17)
    assert found_art.listening_week_start(friday_in_berlin) == date(2026, 7, 24)


def test_refresh_history_merges_only_new_live_scrobbles(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    recent_path = tmp_path / "recent.jsonl"
    export_path.write_text(
        json.dumps(
            {
                "scrobbles": [
                    {
                        "artist": "Known Artist",
                        "track": "Known Track",
                        "album": "Album",
                        "date": 1_000_000,
                    }
                ]
            }
        )
    )
    lastfm = FakeLastFm()
    lastfm.recent = (
        LastFmRecentTrack("Known Artist", "Known Track", "Album", 1000),
        LastFmRecentTrack("New Artist", "New Track", "New Album", 1001),
    )

    history, added = found_art.refresh_scrobble_history(
        lastfm,
        export_path=export_path,
        recent_path=recent_path,
        now=datetime(1970, 1, 1, 0, 20, tzinfo=UTC),
    )

    assert added == 1
    assert [scrobble.track for scrobble in history] == [
        "Known Track",
        "New Track",
    ]
    assert not recent_path.exists()
    persisted = json.loads(export_path.read_text())
    assert [record["track"] for record in persisted["scrobbles"]] == [
        "Known Track",
        "New Track",
    ]


def test_seed_selection_combines_recent_annual_and_overall_tracks() -> None:
    history = tuple(
        found_art.TrackHistory(
            artist=f"Artist {index}",
            track=f"Track {index}",
            key=(f"artist{index}", f"track{index}"),
            play_count=100 - index,
            recent_play_count=10 - index if index < 3 else 0,
            annual_play_count=20 - index if index < 6 else 0,
            last_played_ms=1000 - index,
        )
        for index in range(9)
    )

    seeds = found_art.select_seed_tracks(
        history,
        seed_count=6,
        week_start=date(2026, 7, 17),
    )

    assert len(seeds) == 6
    assert {item.source for item in seeds} == {"recent", "annual", "overall"}
    assert len({item.key for item in seeds}) == 6


def test_seed_selection_is_stable_within_week_and_rotates_next_week() -> None:
    history = tuple(
        found_art.TrackHistory(
            artist=f"Artist {index}",
            track=f"Track {index}",
            key=(f"artist{index}", f"track{index}"),
            play_count=100 - index,
            recent_play_count=50 - index,
            annual_play_count=75 - index,
            last_played_ms=1000 - index,
        )
        for index in range(40)
    )

    first = found_art.select_seed_tracks(
        history,
        seed_count=9,
        week_start=date(2026, 7, 17),
    )
    repeated = found_art.select_seed_tracks(
        history,
        seed_count=9,
        week_start=date(2026, 7, 17),
    )
    following = found_art.select_seed_tracks(
        history,
        seed_count=9,
        week_start=date(2026, 7, 24),
    )

    assert first == repeated
    assert {item.key for item in first} != {item.key for item in following}


def test_candidates_exclude_heard_tracks_and_combine_seed_support(
    tmp_path: Path,
) -> None:
    lastfm = FakeLastFm()
    seeds = (seed("Seed One", "Track One"), seed("Seed Two", "Track Two"))
    lastfm.similar[("Seed One", "Track One")] = (
        LastFmSimilarTrack("Heard Artist", "Old Song - Remastered", 1.0),
        LastFmSimilarTrack("New Artist", "New Song", 0.8),
    )
    lastfm.similar[("Seed Two", "Track Two")] = (
        LastFmSimilarTrack("New Artist", "New Song", 0.7),
        LastFmSimilarTrack("Other Artist", "Other Song", 0.9),
    )

    candidates = found_art.gather_candidates(
        lastfm,
        seeds,
        {found_art.canonical_track_key("Heard Artist", "Old Song")},
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 23, tzinfo=UTC),
    )

    assert [item.track for item in candidates] == ["New Song", "Other Song"]
    assert len(candidates[0].supporting_seeds) == 2
    assert len(lastfm.similar_calls) == 2

    found_art.gather_candidates(
        lastfm,
        seeds,
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    assert len(lastfm.similar_calls) == 2

    found_art.gather_candidates(
        lastfm,
        seeds,
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 24, 1, tzinfo=UTC),
    )
    assert len(lastfm.similar_calls) == 4


def test_candidate_order_is_stable_within_week_and_rotates_next_week(
    tmp_path: Path,
) -> None:
    lastfm = FakeLastFm()
    seeds = (seed("Seed Artist", "Seed Track"),)
    lastfm.similar[("Seed Artist", "Seed Track")] = tuple(
        LastFmSimilarTrack(
            f"Candidate Artist {index}",
            f"Candidate Track {index}",
            1 - index / 100,
        )
        for index in range(30)
    )

    first = found_art.gather_candidates(
        lastfm,
        seeds,
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 23, tzinfo=UTC),
    )
    repeated = found_art.gather_candidates(
        lastfm,
        seeds,
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 23, 12, tzinfo=UTC),
    )
    following = found_art.gather_candidates(
        lastfm,
        seeds,
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        now=datetime(2026, 7, 24, 1, tzinfo=UTC),
    )

    assert [item.key for item in first] == [item.key for item in repeated]
    assert [item.key for item in first] != [item.key for item in following]


def test_spotify_resolution_skips_liked_track_and_selects_unliked_match() -> None:
    spotify = FakeSpotify()
    first = candidate("Artist One", "Liked Song", 1.0)
    second = candidate("Artist Two", "Fresh Song", 0.9)
    first_query = blast_from_past.spotify_search_query(
        blast_from_past.Scrobble("Liked Song", "Artist One", "", 0)
    )
    second_query = blast_from_past.spotify_search_query(
        blast_from_past.Scrobble("Fresh Song", "Artist Two", "", 0)
    )
    spotify.search_results[first_query] = [
        spotify_track("liked", "Liked Song", "Artist One"),
        spotify_track("alternate", "Liked Song - Remastered", "Artist One"),
    ]
    spotify.search_results[second_query] = [
        spotify_track("fresh", "Fresh Song", "Artist Two")
    ]
    spotify.liked_ids = {"liked"}

    results, pending = found_art.resolve_spotify_candidates(
        spotify,  # type: ignore[arg-type]
        (first, second),
        blast_from_past.PlaylistState(0, frozenset()),
        count=1,
    )

    assert [result.action for result in results] == ["liked", "added"]
    assert [match.spotify_id for match in pending] == ["fresh"]


def test_spotify_resolution_recognizes_alternate_playlist_edition() -> None:
    spotify = FakeSpotify()
    existing = candidate("Artist", "Song - 2011 Remastered", 1.0)

    results, pending = found_art.resolve_spotify_candidates(
        spotify,  # type: ignore[arg-type]
        (existing,),
        blast_from_past.PlaylistState(
            1,
            frozenset({"different-spotify-id"}),
            frozenset({found_art.canonical_track_key("Artist", "Song")}),
        ),
        count=1,
    )

    assert [result.action for result in results] == ["already present"]
    assert pending == ()


def test_spotify_resolution_selects_only_one_track_per_artist() -> None:
    spotify = FakeSpotify()
    candidates = (
        candidate("Repeated Artist", "First Song", 1.0),
        candidate("Repeated Artist", "Second Song", 0.9),
        candidate("Other Artist", "Third Song", 0.8),
    )
    for index, item in enumerate(candidates):
        query = blast_from_past.spotify_search_query(
            blast_from_past.Scrobble(item.track, item.artist, "", 0)
        )
        spotify.search_results[query] = [
            spotify_track(str(index), item.track, item.artist)
        ]

    results, pending = found_art.resolve_spotify_candidates(
        spotify,  # type: ignore[arg-type]
        candidates,
        blast_from_past.PlaylistState(0, frozenset()),
        count=2,
    )

    assert [result.action for result in results] == [
        "added",
        "artist already selected",
        "added",
    ]
    assert [match.spotify_id for match in pending] == ["0", "2"]


def test_found_art_configuration_parsing_and_validation() -> None:
    assert (
        found_art.parse_found_art_playlist_id("spotify:playlist:playlistid")
        == "playlistid"
    )
    assert found_art.validate_lastfm_configuration(" key ", " user ") == (
        "key",
        "user",
    )

    with pytest.raises(found_art.FoundArtConfigError, match="FOUND_ART_PLAYLIST"):
        found_art.parse_found_art_playlist_id(None)
    with pytest.raises(found_art.FoundArtConfigError, match="LASTFM_API_KEY"):
        found_art.validate_lastfm_configuration(" ", "user")
    with pytest.raises(found_art.FoundArtConfigError, match="LASTFM_USERNAME"):
        found_art.validate_lastfm_configuration("key", None)


def test_listening_week_accepts_date_naive_datetime_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert found_art.listening_week_start(date(2026, 7, 23)) == date(2026, 7, 17)
    assert found_art.listening_week_start(datetime(2026, 7, 23, 12)) == date(
        2026, 7, 17
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 24, 12, tzinfo=tz)

    monkeypatch.setattr(found_art, "datetime", FixedDateTime)
    assert found_art.listening_week_start() == date(2026, 7, 24)


def test_refresh_history_translates_shared_state_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise found_art.shared_scrobble_history.ScrobbleHistoryError("bad history")

    monkeypatch.setattr(
        found_art.shared_scrobble_history,
        "refresh_scrobble_history",
        fail,
    )

    with pytest.raises(found_art.FoundArtStateError, match="bad history"):
        found_art.refresh_scrobble_history(FakeLastFm())


def test_track_history_aggregation_handles_empty_old_and_renamed_scrobbles() -> None:
    assert found_art.aggregate_track_history(()) == ()
    day_ms = int(24 * 60 * 60 * 1000)
    scrobbles = (
        blast_from_past.Scrobble("", "Ignored", "", 0),
        blast_from_past.Scrobble("Song", "Old spelling", "", 0),
        blast_from_past.Scrobble("Song", "OLD SPELLING", "", 300 * day_ms),
        blast_from_past.Scrobble("Song", "Old Spelling", "", 400 * day_ms),
    )

    history = found_art.aggregate_track_history(scrobbles)

    assert len(history) == 1
    assert history[0].artist == "Old Spelling"
    assert history[0].play_count == 3
    assert history[0].recent_play_count == 1
    assert history[0].annual_play_count == 2


def test_seed_selection_rejects_invalid_or_insufficient_history() -> None:
    with pytest.raises(found_art.FoundArtConfigError, match="at least 1"):
        found_art.select_seed_tracks((), seed_count=0)
    with pytest.raises(found_art.FoundArtStateError, match="No tracks"):
        found_art.select_seed_tracks((), seed_count=1)

    same_artist = tuple(
        found_art.TrackHistory(
            artist="Artist",
            track=f"Track {index}",
            key=("artist", f"track-{index}"),
            play_count=10 - index,
            recent_play_count=10 - index,
            annual_play_count=10 - index,
            last_played_ms=index,
        )
        for index in range(4)
    )
    with pytest.raises(found_art.FoundArtStateError, match="sufficiently diverse"):
        found_art.select_seed_tracks(
            same_artist,
            seed_count=4,
            week_start=date(2026, 7, 17),
        )


def test_similar_cache_rejects_corruption_and_unwritable_destination(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not-json")
    with pytest.raises(found_art.FoundArtStateError, match="cache is invalid"):
        found_art._load_similar_cache(cache_path)

    cache_path.write_text(json.dumps({"version": 2, "entries": []}))
    with pytest.raises(found_art.FoundArtStateError, match="cache is invalid"):
        found_art._load_similar_cache(cache_path)

    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("file")
    with pytest.raises(found_art.FoundArtStateError, match="Could not save"):
        found_art._save_similar_cache(
            {"version": 1, "entries": {}},
            blocked_parent / "cache.json",
        )


def test_cached_similar_tracks_validates_shape_and_week() -> None:
    week = date(2026, 7, 17)
    assert found_art._cached_similar_tracks("bad", week_start=week) is None
    assert (
        found_art._cached_similar_tracks(
            {"fetched_at": "2026-07-23T12:00:00", "tracks": []},
            week_start=week,
        )
        == ()
    )
    assert (
        found_art._cached_similar_tracks(
            {"fetched_at": "2026-07-24T12:00:00+00:00", "tracks": []},
            week_start=week,
        )
        is None
    )
    assert (
        found_art._cached_similar_tracks(
            {"fetched_at": "2026-07-23T12:00:00+00:00", "tracks": "bad"},
            week_start=week,
        )
        is None
    )
    assert (
        found_art._cached_similar_tracks(
            {"fetched_at": "bad", "tracks": []},
            week_start=week,
        )
        is None
    )


def test_previous_additions_are_read_and_invalid_logs_are_rejected(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.jsonl"
    assert found_art.previously_added_track_keys(missing) == set()

    log_path = tmp_path / "found-art.jsonl"
    log_path.write_text(
        "\n"
        + json.dumps(
            {
                "results": [
                    "bad",
                    {"action": "would add"},
                    {
                        "action": "added",
                        "candidate": {"artist": "Artist", "track": "Track"},
                    },
                ]
            }
        )
        + "\n"
    )
    assert found_art.previously_added_track_keys(log_path) == {
        found_art.canonical_track_key("Artist", "Track")
    }

    log_path.write_text(json.dumps({"results": "bad"}) + "\n")
    with pytest.raises(found_art.FoundArtStateError, match="at line 1"):
        found_art.previously_added_track_keys(log_path)

    log_path.write_text(
        json.dumps({"results": [{"action": "added", "candidate": "bad"}]}) + "\n"
    )
    with pytest.raises(found_art.FoundArtStateError, match="at line 1"):
        found_art.previously_added_track_keys(log_path)


def test_gather_candidates_validates_limit_and_emits_progress(
    tmp_path: Path,
) -> None:
    with pytest.raises(found_art.FoundArtConfigError, match="at least 1"):
        found_art.gather_candidates(
            FakeLastFm(),
            (),
            set(),
            candidate_pool_size=0,
        )

    lastfm = FakeLastFm()
    item = seed("Seed", "Track")
    lastfm.similar[(item.artist, item.track)] = (
        LastFmSimilarTrack("Candidate", "Track", 0.5),
    )
    progress: list[str] = []
    candidates = found_art.gather_candidates(
        lastfm,
        (item,),
        set(),
        cache_path=tmp_path / "cache.json",
        log_path=tmp_path / "log.jsonl",
        week_start=date(2026, 7, 17),
        now=datetime(2026, 7, 23, tzinfo=UTC),
        progress_callback=progress.append,
    )

    assert len(candidates) == 1
    assert progress == ["Getting Last.fm neighbors for seed 1/1"]


def test_spotify_resolution_covers_no_match_duplicate_and_dry_run() -> None:
    spotify = FakeSpotify()
    candidates = (
        candidate("No Match", "Missing", 1.0),
        candidate("First Artist", "First", 0.9),
        candidate("Second Artist", "Second", 0.8),
    )
    for item in candidates[1:]:
        query = blast_from_past.spotify_search_query(
            blast_from_past.Scrobble(item.track, item.artist, "", 0)
        )
        spotify.search_results[query] = [
            spotify_track("same-id", item.track, item.artist)
        ]
    progress: list[str] = []

    results, pending = found_art.resolve_spotify_candidates(
        spotify,  # type: ignore[arg-type]
        candidates,
        blast_from_past.PlaylistState(0, frozenset()),
        count=2,
        dry_run=True,
        progress_callback=progress.append,
    )

    assert [result.action for result in results] == [
        "no Spotify match",
        "would add",
        "duplicate",
    ]
    assert [match.spotify_id for match in pending] == ["same-id"]
    assert progress[-1] == "Checking candidates against Spotify Liked Songs"


def test_found_art_log_round_trip_and_write_failure(tmp_path: Path) -> None:
    match = blast_from_past.SpotifyTrackMatch(
        spotify_id="track-id",
        uri="spotify:track:track-id",
        track="Track",
        artists=("Artist",),
        album="Album",
        search_rank=1,
        track_similarity=1.0,
        album_similarity=None,
        popularity=50,
        liked=False,
    )
    summary = found_art.FoundArtSummary(
        generated_at=datetime(2026, 7, 23, tzinfo=UTC),
        week_start=date(2026, 7, 17),
        playlist_id="playlist",
        requested_count=1,
        seed_count=1,
        history_tracks=1,
        history_scrobbles=2,
        live_scrobbles_added=0,
        candidate_count=1,
        playlist_length_before=0,
        playlist_length_after=1,
        dry_run=False,
        seeds=(seed("Seed", "Track"),),
        results=(
            found_art.FoundArtResult(
                candidate("Artist", "Track", 1),
                match,
                "added",
            ),
        ),
    )
    log_path = tmp_path / "log.jsonl"

    found_art.append_found_art_log(summary, log_path)

    record = json.loads(log_path.read_text())
    assert record["results"][0]["match"]["spotify_id"] == "track-id"
    assert summary.added == 1
    assert summary.selected == 1

    blocked = tmp_path / "blocked"
    blocked.write_text("file")
    with pytest.raises(found_art.FoundArtStateError, match="Could not write"):
        found_art.append_found_art_log(summary, blocked / "log.jsonl")


@pytest.mark.parametrize(
    ("count", "maximum", "seed_count", "message"),
    [
        (1, 10, 1, "either count"),
        (0, None, 1, "Count"),
        (None, 0, 1, "Maximum"),
        (1, None, 0, "Seed count"),
    ],
)
def test_run_found_art_rejects_invalid_limits(
    count: int | None,
    maximum: int | None,
    seed_count: int,
    message: str,
) -> None:
    with pytest.raises(found_art.FoundArtConfigError, match=message):
        found_art.run_found_art(
            object(),  # type: ignore[arg-type]
            FakeLastFm(),
            "playlist",
            count=count,
            max_playlist_length=maximum,
            seed_count=seed_count,
        )


def test_run_found_art_orchestrates_addition_and_full_playlist_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = [blast_from_past.Scrobble("Seed", "Artist", "", 1)]
    chosen_seed = seed("Artist", "Seed")
    chosen_candidate = candidate("New Artist", "New Track", 1)
    match = blast_from_past.SpotifyTrackMatch(
        spotify_id="new-id",
        uri="spotify:track:new-id",
        track="New Track",
        artists=("New Artist",),
        album="Album",
        search_rank=1,
        track_similarity=1,
        album_similarity=None,
        popularity=1,
        liked=False,
    )
    playlist = blast_from_past.PlaylistState(2, frozenset())
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        found_art,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: (history, 1),
    )
    monkeypatch.setattr(
        found_art,
        "select_seed_tracks",
        lambda *_args, **_kwargs: (chosen_seed,),
    )
    monkeypatch.setattr(
        found_art,
        "gather_candidates",
        lambda *_args, **_kwargs: (chosen_candidate,),
    )
    monkeypatch.setattr(
        found_art,
        "resolve_spotify_candidates",
        lambda *_args, **_kwargs: (
            (found_art.FoundArtResult(chosen_candidate, match, "added"),),
            (match,),
        ),
    )
    monkeypatch.setattr(
        found_art.blast_from_past,
        "load_playlist_state",
        lambda *_args, **_kwargs: playlist,
    )
    monkeypatch.setattr(
        found_art.blast_from_past,
        "add_spotify_matches",
        lambda _sp, playlist_id, matches: calls.append(
            (playlist_id, [item.spotify_id for item in matches])
        ),
    )
    monkeypatch.setattr(
        found_art,
        "append_found_art_log",
        lambda summary, _path: calls.append(("log", summary)),
    )
    progress: list[str] = []

    summary = found_art.run_found_art(
        object(),  # type: ignore[arg-type]
        FakeLastFm(),
        "playlist",
        count=1,
        seed_count=1,
        now=datetime(2026, 7, 23, tzinfo=UTC),
        export_path=tmp_path / "history.json",
        log_path=tmp_path / "log.jsonl",
        progress_callback=progress.append,
    )

    assert summary.playlist_length_after == 3
    assert calls[0] == ("playlist", ["new-id"])
    assert "Adding 1 tracks to Found Art" in progress

    calls.clear()
    noop = found_art.run_found_art(
        object(),  # type: ignore[arg-type]
        FakeLastFm(),
        "playlist",
        count=None,
        max_playlist_length=2,
        seed_count=1,
        dry_run=True,
        now=datetime(2026, 7, 23, tzinfo=UTC),
        log_path=tmp_path / "log.jsonl",
    )
    assert noop.requested_count == 0
    assert noop.seeds == ()
    assert noop.results == ()
    assert calls[0][0] == "log"
