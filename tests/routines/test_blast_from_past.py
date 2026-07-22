"""Tests for the a-blast-from-the-past selection routine."""

import base64
import gzip
import json
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from spotify_manager.routines import blast_from_past


def make_scrobble(number: int) -> blast_from_past.Scrobble:
    """Return a numbered scrobble for pagination assertions."""
    return blast_from_past.Scrobble(
        track=f"Track {number}",
        artist="Artist",
        album="Album",
        timestamp_ms=10_000 - number,
    )


def spotify_track(
    spotify_id: str,
    track: str,
    artist: str,
    album: str,
    popularity: int = 50,
) -> dict[str, object]:
    """Return one Spotify-shaped search result."""
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": track,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "popularity": popularity,
    }


class FakeSpotify:
    """Small Spotify stand-in for search, library, and playlist operations."""

    def __init__(self) -> None:
        self.playlist_tracks: list[dict[str, object]] = []
        self.search_results: dict[str, list[dict[str, object]]] = {}
        self.liked_ids: set[str] = set()
        self.search_calls: list[str] = []
        self.liked_calls: list[list[str]] = []
        self.posts: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, limit: int, offset: int) -> dict[str, object]:
        assert path == "playlists/blast/items"
        items = [
            {"item": track} for track in self.playlist_tracks[offset : offset + limit]
        ]
        return {
            "items": items,
            "total": len(self.playlist_tracks),
            "next": (
                "next" if offset + len(items) < len(self.playlist_tracks) else None
            ),
        }

    def search(
        self,
        q: str,
        limit: int,
        offset: int,
        **kwargs: str,
    ) -> dict[str, object]:
        assert kwargs["type"] == "track"
        assert limit == blast_from_past.SPOTIFY_SEARCH_LIMIT
        assert offset == 0
        self.search_calls.append(q)
        return {"tracks": {"items": self.search_results.get(q, [])}}

    def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        self.liked_calls.append(ids)
        return [spotify_id in self.liked_ids for spotify_id in ids]

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, str]:
        self.posts.append((path, payload))
        return {"snapshot_id": "snapshot"}


def test_load_scrobbles_uses_berlin_dates_and_newest_first(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        json.dumps(
            {
                "scrobbles": [
                    {
                        "track": "Earlier",
                        "artist": "Artist",
                        "album": "",
                        "date": 1196118653000,
                    },
                    {
                        "track": "Later",
                        "artist": "Artist",
                        "album": "Album",
                        "date": 1196122253000,
                    },
                ]
            }
        )
    )

    by_date = blast_from_past.load_scrobbles_by_date(export_path)

    assert list(by_date) == [date(2007, 11, 27)]
    assert [item.track for item in by_date[date(2007, 11, 27)]] == [
        "Later",
        "Earlier",
    ]
    assert by_date[date(2007, 11, 27)][1].album == ""


def test_load_scrobbles_falls_back_to_adjacent_gzip(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        "version https://git-lfs.github.com/spec/v1\n",
        encoding="utf-8",
    )
    payload = {
        "scrobbles": [
            {
                "track": "Compressed track",
                "artist": "Artist",
                "album": "Album",
                "date": 1196122253000,
            }
        ]
    }
    with gzip.open(f"{export_path}.gz", mode="wt", encoding="utf-8") as output:
        json.dump(payload, output)

    by_date = blast_from_past.load_scrobbles_by_date(export_path)

    assert by_date[date(2007, 11, 27)][0].track == "Compressed track"


def test_load_scrobbles_reassembles_compressed_parts(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        "version https://git-lfs.github.com/spec/v1\n",
        encoding="utf-8",
    )
    payload = {
        "scrobbles": [
            {
                "track": "Split compressed track",
                "artist": "Artist",
                "album": "Album",
                "date": 1196122253000,
            }
        ]
    }
    compressed = gzip.compress(json.dumps(payload).encode())
    split_at = len(compressed) // 2
    Path(f"{export_path}.gz.part-aa").write_bytes(compressed[:split_at])
    Path(f"{export_path}.gz.part-ab").write_bytes(compressed[split_at:])

    by_date = blast_from_past.load_scrobbles_by_date(export_path)

    assert by_date[date(2007, 11, 27)][0].track == "Split compressed track"


def test_load_scrobbles_reassembles_encoded_parts(tmp_path: Path) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        "version https://git-lfs.github.com/spec/v1\n",
        encoding="utf-8",
    )
    payload = {
        "scrobbles": [
            {
                "track": "Encoded compressed track",
                "artist": "Artist",
                "album": "Album",
                "date": 1196122253000,
            }
        ]
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode()))
    split_at = len(encoded) // 2
    Path(f"{export_path}.gz.b64.part-aa").write_bytes(encoded[:split_at])
    Path(f"{export_path}.gz.b64.part-ab").write_bytes(encoded[split_at:])

    by_date = blast_from_past.load_scrobbles_by_date(export_path)

    assert by_date[date(2007, 11, 27)][0].track == "Encoded compressed track"


def test_fetch_random_indexes_reads_unique_set_and_server_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        headers = {"Date": "Wed, 22 Jul 2026 13:00:52 GMT"}

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"3 1\n"

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(blast_from_past, "urlopen", fake_urlopen)

    result = blast_from_past.fetch_random_indexes(5, 2)

    assert result.indexes == (3, 1)
    assert result.generated_at == datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)
    request = captured["request"]
    query = parse_qs(urlparse(request.full_url).query)  # type: ignore[attr-defined]
    assert query["sets"] == ["1"]
    assert query["num"] == ["2"]
    assert query["min"] == ["0"]
    assert query["max"] == ["4"]
    assert query["rnd"] == ["new"]
    assert captured["timeout"] == blast_from_past.RANDOM_ORG_TIMEOUT_SECONDS


def test_fetch_random_indexes_rejects_missing_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        headers: dict[str, str] = {}

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"0\n"

    monkeypatch.setattr(
        blast_from_past,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    with pytest.raises(blast_from_past.RandomOrgError, match="timestamp"):
        blast_from_past.fetch_random_indexes(1, 1)


def test_fetch_random_timestamp_uses_minimal_random_org_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_at = datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)
    calls: list[tuple[int, int]] = []

    def fetch(population_size: int, count: int) -> blast_from_past.RandomIndexSet:
        calls.append((population_size, count))
        return blast_from_past.RandomIndexSet((1,), generated_at)

    monkeypatch.setattr(blast_from_past, "fetch_random_indexes", fetch)

    assert blast_from_past.fetch_random_timestamp() is generated_at
    assert calls == [(2, 1)]


def test_page_seven_requires_minute_zero_and_hour_after_twelve() -> None:
    assert (
        blast_from_past.page_for_timestamp(
            datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
            7,
        )
        == 7
    )
    assert (
        blast_from_past.page_for_timestamp(
            datetime(2026, 7, 22, 12, 0, 52, tzinfo=UTC),
            7,
        )
        == 6
    )
    assert (
        blast_from_past.page_for_timestamp(
            datetime(2026, 7, 22, 13, 1, 52, tzinfo=UTC),
            7,
        )
        == 6
    )


def test_select_scrobble_wraps_seconds_on_seventh_page() -> None:
    scrobbles = [make_scrobble(number) for number in range(314)]

    selection = blast_from_past.select_scrobble(
        date(2020, 1, 1),
        10,
        scrobbles,
        datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
    )

    assert selection.page == 7
    assert selection.total_pages == 7
    assert selection.direction == "top down"
    assert selection.position == 11
    assert selection.scrobble.track == "Track 310"


def test_select_scrobble_wraps_page_and_partial_page_position() -> None:
    scrobbles = [make_scrobble(number) for number in range(55)]

    selection = blast_from_past.select_scrobble(
        date(2020, 1, 1),
        10,
        scrobbles,
        datetime(2026, 7, 22, 12, 40, 8, tzinfo=UTC),
    )

    assert selection.page == 2
    assert selection.position == 4
    assert selection.scrobble.track == "Track 53"


def test_select_scrobble_can_count_from_bottom() -> None:
    scrobbles = [make_scrobble(number) for number in range(50)]

    selection = blast_from_past.select_scrobble(
        date(2020, 1, 1),
        10,
        scrobbles,
        datetime(2026, 7, 22, 12, 15, 3, tzinfo=UTC),
    )

    assert selection.direction == "bottom up"
    assert selection.position == 4
    assert selection.scrobble.track == "Track 46"


def test_select_batch_uses_one_timestamp_for_unique_date_indexes(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "lastfm.json"
    export_path.write_text(
        json.dumps(
            {
                "scrobbles": [
                    {
                        "track": f"Track {day}",
                        "artist": "Artist",
                        "album": "Album",
                        "date": int(
                            datetime(2020, 1, day, 12, tzinfo=UTC).timestamp() * 1000
                        ),
                    }
                    for day in (1, 2, 3)
                ]
            }
        )
    )
    generated_at = datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)

    batch = blast_from_past.select_blast_from_past(
        count=2,
        path=export_path,
        today=date(2026, 7, 22),
        random_index_reader=lambda population, count: blast_from_past.RandomIndexSet(
            (2, 0), generated_at
        ),
    )

    assert batch.generated_at is generated_at
    assert batch.available_dates == 3
    assert [selection.selected_date.day for selection in batch.selections] == [3, 1]
    assert [selection.scrobble.track for selection in batch.selections] == [
        "Track 3",
        "Track 1",
    ]


def test_spotify_matching_allows_known_qualifiers_but_requires_names() -> None:
    scrobble = blast_from_past.Scrobble(
        track="Enjoy the Silence",
        artist="Depeche Mode",
        album="Violator",
        timestamp_ms=1,
    )

    match = blast_from_past.matching_spotify_track(
        scrobble,
        spotify_track(
            "qualified",
            "Enjoy the Silence - 2006 Remaster",
            "Depeche Mode",
            "Violator (Deluxe Edition)",
        ),
        1,
    )

    assert match is not None
    assert match.track_similarity == 1.0
    assert match.album_similarity == 1.0
    assert (
        blast_from_past.matching_spotify_track(
            scrobble,
            spotify_track(
                "wrong-artist",
                "Enjoy the Silence",
                "Depeche Mode Tribute",
                "Violator",
            ),
            2,
        )
        is None
    )
    wrong_album = blast_from_past.matching_spotify_track(
        scrobble,
        spotify_track(
            "wrong-album",
            "Enjoy the Silence",
            "Depeche Mode",
            "Some Great Reward",
        ),
        3,
    )
    assert wrong_album is not None
    assert blast_from_past.preferred_spotify_match((wrong_album,), set()) is None
    assert (
        blast_from_past.preferred_spotify_match(
            (wrong_album,),
            {"wrong-album"},
        )
        is not None
    )


def test_missing_scrobble_album_does_not_restrict_spotify_album() -> None:
    scrobble = blast_from_past.Scrobble(
        track="Song",
        artist="Artist",
        album="",
        timestamp_ms=1,
    )

    match = blast_from_past.matching_spotify_track(
        scrobble,
        spotify_track("track", "Song", "Artist", "Any release"),
        1,
    )

    assert match is not None
    assert match.album_similarity is None


def test_preferred_spotify_match_puts_liked_status_first() -> None:
    unliked = blast_from_past.SpotifyTrackMatch(
        spotify_id="unliked",
        uri="spotify:track:unliked",
        track="Track",
        artists=("Artist",),
        album="Album",
        search_rank=1,
        track_similarity=1.0,
        album_similarity=1.0,
        popularity=100,
    )
    liked = blast_from_past.SpotifyTrackMatch(
        spotify_id="liked",
        uri="spotify:track:liked",
        track="Track - Remastered",
        artists=("Artist",),
        album="Entirely Different Album",
        search_rank=2,
        track_similarity=0.95,
        album_similarity=0.2,
        popularity=10,
    )

    selected = blast_from_past.preferred_spotify_match(
        (unliked, liked),
        {"liked"},
    )

    assert selected is not None
    assert selected.spotify_id == "liked"
    assert selected.liked is True


def test_spotify_routine_prefers_liked_match_and_adds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sp = FakeSpotify()
    sp.playlist_tracks = [spotify_track("existing", "Old", "Artist", "Album")]
    first_scrobble = blast_from_past.Scrobble(
        track="Track",
        artist="Artist",
        album="Album",
        timestamp_ms=1,
    )
    second_scrobble = blast_from_past.Scrobble(
        track="Missing",
        artist="Artist",
        album="Album",
        timestamp_ms=2,
    )
    selections = (
        blast_from_past.ScrobbleSelection(
            date(2010, 1, 1),
            1,
            1,
            1,
            1,
            "top down",
            1,
            first_scrobble,
        ),
        blast_from_past.ScrobbleSelection(
            date(2010, 1, 2),
            2,
            1,
            1,
            1,
            "top down",
            1,
            second_scrobble,
        ),
    )
    batch = blast_from_past.BlastFromPastBatch(
        generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
        cutoff_date=date(2021, 12, 31),
        available_dates=100,
        selections=selections,
    )
    first_query = blast_from_past.spotify_search_query(first_scrobble)
    second_query = blast_from_past.spotify_search_query(second_scrobble)
    sp.search_results[first_query] = [
        spotify_track("unliked", "Track", "Artist", "Album", 100),
        spotify_track(
            "liked",
            "Track - 2011 Remaster",
            "Artist",
            "Entirely Different Album",
            10,
        ),
    ]
    sp.search_results[second_query] = [
        spotify_track("wrong", "Different", "Artist", "Album")
    ]
    sp.liked_ids = {"liked"}
    monkeypatch.setattr(
        blast_from_past,
        "select_blast_from_past",
        lambda **_kwargs: batch,
    )

    summary = blast_from_past.add_blast_from_past_to_spotify(
        sp,  # type: ignore[arg-type]
        "blast",
        count=2,
    )

    assert summary.added == 1
    assert summary.playlist_length_before == 1
    assert summary.playlist_length_after == 2
    assert [result.action for result in summary.results] == ["added", "no match"]
    assert summary.results[0].match is not None
    assert summary.results[0].match.spotify_id == "liked"
    assert sp.liked_calls == [["unliked", "liked"]]
    assert sp.posts == [
        (
            "playlists/blast/items",
            {"uris": ["spotify:track:liked"]},
        )
    ]


def test_maximum_playlist_length_only_selects_open_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sp = FakeSpotify()
    sp.playlist_tracks = [
        spotify_track(str(index), f"Track {index}", "Artist", "Album")
        for index in range(3)
    ]
    calls: list[int] = []
    batch = blast_from_past.BlastFromPastBatch(
        generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
        cutoff_date=date(2021, 12, 31),
        available_dates=100,
        selections=(),
    )

    def select(**kwargs: object) -> blast_from_past.BlastFromPastBatch:
        calls.append(int(str(kwargs["count"])))
        return batch

    monkeypatch.setattr(blast_from_past, "select_blast_from_past", select)

    summary = blast_from_past.add_blast_from_past_to_spotify(
        sp,  # type: ignore[arg-type]
        "blast",
        count=None,
        max_playlist_length=5,
    )

    assert calls == [2]
    assert summary.requested_count == 2


def test_full_maximum_playlist_skips_random_org_and_search() -> None:
    sp = FakeSpotify()
    sp.playlist_tracks = [spotify_track("one", "Track", "Artist", "Album")]

    summary = blast_from_past.add_blast_from_past_to_spotify(
        sp,  # type: ignore[arg-type]
        "blast",
        count=None,
        max_playlist_length=1,
    )

    assert summary.batch is None
    assert summary.requested_count == 0
    assert sp.search_calls == []
    assert sp.posts == []
