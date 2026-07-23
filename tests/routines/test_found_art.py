"""Tests for Last.fm-style Found Art recommendations."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

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
    assert len(recent_path.read_text().splitlines()) == 1


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
