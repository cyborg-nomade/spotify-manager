"""Tests for the round-week discography planner."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import discography
from spotify_manager.routines import new_wine


def raw_release(
    release_id: str,
    name: str,
    *,
    release_date: str,
    album_type: str = "album",
    album_group: str = "album",
    total_tracks: int = 10,
    artist_id: str = "artist",
) -> dict[str, object]:
    """Build one simplified Spotify artist-albums response."""
    return {
        "id": release_id,
        "uri": f"spotify:album:{release_id}",
        "name": name,
        "release_date": release_date,
        "album_type": album_type,
        "album_group": album_group,
        "total_tracks": total_tracks,
        "artists": [{"id": artist_id, "name": "Artist"}],
    }


def catalog_release(
    release_id: str,
    *,
    default: bool = True,
) -> discography.CatalogRelease:
    """Build one selected catalog release."""
    return discography.CatalogRelease(
        spotify_id=release_id,
        uri=f"spotify:album:{release_id}",
        name=release_id,
        release_type="Album" if default else "Live",
        release_date="2020-01-01",
        chronology_date="2020-01-01",
        total_tracks=10,
        identity=release_id,
        saved=False,
        plain=True,
        edition_rank=0,
        default=default,
    )


def playlist_track(
    track_id: str,
    artist_id: str,
    artist_name: str,
) -> new_wine.PlaylistTrack:
    """Build one playlist marker for queue-loading tests."""
    release = new_wine.ReleaseCandidate(
        spotify_id=f"release-{track_id}",
        uri=f"spotify:album:release-{track_id}",
        name="Release",
        release_type="Album",
        release_date="2020-01-01",
        total_tracks=10,
        primary_artist_id=artist_id,
        primary_artist_name=artist_name,
    )
    return new_wine.PlaylistTrack(
        spotify_id=track_id,
        uri=f"spotify:track:{track_id}",
        name=track_id,
        primary_artist_id=artist_id,
        primary_artist_name=artist_name,
        release=release,
    )


class CatalogSpotify:
    """Small Spotify simulation for release filtering and edition choice."""

    def __init__(self, releases: list[dict[str, object]]) -> None:
        self.releases = releases

    def artist_albums(
        self,
        artist_id: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        assert artist_id == "artist"
        assert include_groups == "album,single,compilation"
        assert limit == 10
        page = self.releases[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(self.releases) else None,
        }

    def current_user_saved_albums_contains(
        self,
        album_ids: list[str],
    ) -> list[bool]:
        return [album_id == "album-deluxe" for album_id in album_ids]


def test_release_catalog_uses_studio_defaults_and_offers_non_studio() -> None:
    """The default mirrors Slow Listening while live/compilation stays optional."""
    spotify = CatalogSpotify(
        [
            raw_release("album", "Record", release_date="2000-01-01"),
            raw_release(
                "album-deluxe",
                "Record (Deluxe Edition)",
                release_date="2010-01-01",
            ),
            raw_release("live", "Live at Home", release_date="2002-01-01"),
            raw_release(
                "compilation",
                "Collected",
                release_date="2003-01-01",
                album_type="compilation",
                album_group="compilation",
            ),
            raw_release(
                "ep",
                "Small Record EP",
                release_date="2004-01-01",
                album_type="single",
                album_group="single",
                total_tracks=4,
            ),
            raw_release(
                "single",
                "One Song",
                release_date="2005-01-01",
                album_type="single",
                album_group="single",
                total_tracks=1,
            ),
        ]
    )

    releases = discography.load_release_catalog(
        spotify,  # type: ignore[arg-type]
        "artist",
        lambda operation, _description: operation(),
    )

    by_id = {release.spotify_id: release for release in releases}
    assert set(by_id) == {"album-deluxe", "live", "compilation", "ep"}
    assert by_id["album-deluxe"].default is True
    assert by_id["album-deluxe"].saved is True
    assert by_id["album-deluxe"].chronology_date == "2000-01-01"
    assert by_id["live"].release_type == "Live"
    assert by_id["live"].default is False
    assert by_id["compilation"].release_type == "Compilation"
    assert by_id["ep"].release_type == "EP"
    assert by_id["ep"].default is True


def test_release_index_parser_accepts_ranges_and_rejects_reverse_ranges() -> None:
    assert discography.parse_release_indexes("1,3-5,3", 5) == (1, 3, 4, 5)
    assert discography.format_release_indexes((1, 2, 3, 5)) == "1-3,5"
    with pytest.raises(ValueError):
        discography.parse_release_indexes("4-2", 5)
    with pytest.raises(ValueError):
        discography.parse_release_indexes("6", 5)


def test_new_state_starts_with_the_requeue(tmp_path: Path) -> None:
    state = discography.load_state(tmp_path / "missing.json")
    assert state["next_queue"] == "requeue"
    assert discography._next_start_queue("requeue") == "memory_lane"
    assert discography._next_start_queue("memory_lane") == "newfoundland"
    assert discography._next_start_queue("newfoundland") == "requeue"


def test_artist_queues_keep_first_seen_order_and_all_unique_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlists = {
        "nf": [
            playlist_track("a-1", "a", "Artist A"),
            playlist_track("b-1", "b", "Artist B"),
            playlist_track("a-1", "a", "Artist A"),
            playlist_track("a-2", "a", "Artist A"),
        ],
        "ml": [playlist_track("a-3", "a", "Artist A")],
        "rq": [],
        "q3": [
            playlist_track("a-4", "a", "Artist A"),
            playlist_track("a-4", "a", "Artist A"),
        ],
    }
    monkeypatch.setattr(
        discography.new_wine,
        "load_playlist_tracks",
        lambda _spotify, playlist_id, _retry: playlists[playlist_id],
    )

    queues, markers = discography._load_artist_queues(
        object(),  # type: ignore[arg-type]
        {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"},
        lambda operation, _description: operation(),
        "q3",
    )

    assert [artist.spotify_id for artist in queues["newfoundland"]] == ["a", "b"]
    assert queues["requeue"] == ()
    assert [(marker.queue, marker.uris) for marker in markers["a"]] == [
        ("newfoundland", ("spotify:track:a-1", "spotify:track:a-2")),
        ("memory_lane", ("spotify:track:a-3",)),
        ("queue_3", ("spotify:track:a-4",)),
    ]


@pytest.mark.parametrize("failing_playlist", ["nf", "q3"])
def test_artist_queue_loading_translates_playlist_errors(
    monkeypatch: pytest.MonkeyPatch,
    failing_playlist: str,
) -> None:
    def load(_spotify, playlist_id, _retry):
        if playlist_id == failing_playlist:
            raise new_wine.NewWineError("playlist unavailable")
        return ()

    monkeypatch.setattr(discography.new_wine, "load_playlist_tracks", load)

    with pytest.raises(discography.DiscographyError, match="playlist unavailable"):
        discography._load_artist_queues(
            object(),  # type: ignore[arg-type]
            {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"},
            lambda operation, _description: operation(),
            "q3",
        )


def test_plan_peruses_the_next_queue_for_an_artist_that_fits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A later artist can fill the remainder when the next queue head cannot."""
    queues = {
        "newfoundland": (discography.QueueArtist("a", "Artist A", "newfoundland"),),
        "memory_lane": (
            discography.QueueArtist("b", "Artist B", "memory_lane"),
            discography.QueueArtist("c", "Artist C", "memory_lane"),
        ),
        "requeue": (discography.QueueArtist("d", "Artist D", "requeue"),),
    }
    marker_map = {
        artist_id: (
            discography.ArtistMarkers(
                queue=queue,
                playlist_id=queue,
                uris=(f"spotify:track:{artist_id}",),
            ),
        )
        for artist_id, queue in {
            "a": "newfoundland",
            "b": "memory_lane",
            "c": "memory_lane",
            "d": "requeue",
        }.items()
    }
    marker_map["a"] += (
        discography.ArtistMarkers(
            queue="queue_3",
            playlist_id="q3",
            uris=("spotify:track:a-q3",),
        ),
    )
    marker_map["c"] += (
        discography.ArtistMarkers(
            queue="queue_3",
            playlist_id="q3",
            uris=("spotify:track:c-q3",),
        ),
    )
    counts = {"a": 4, "b": 8, "c": 6, "d": 2}
    prompted: list[str] = []
    monkeypatch.setattr(
        discography,
        "_load_artist_queues",
        lambda *_args: (queues, marker_map),
    )
    monkeypatch.setattr(
        discography,
        "load_release_catalog",
        lambda _spotify, artist_id, _retry: tuple(
            catalog_release(f"{artist_id}-{index}")
            for index in range(counts[artist_id])
        ),
    )

    state_path = tmp_path / "state.json"
    discography.save_next_queue("newfoundland", state_path)

    def select_defaults(
        artist: discography.QueueArtist,
        releases: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        prompted.append(artist.spotify_id)
        return tuple(release.spotify_id for release in releases if release.default)

    plan = discography.build_discography_plan(
        object(),  # type: ignore[arg-type]
        {
            "newfoundland": "nf",
            "memory_lane": "ml",
            "requeue": "rq",
        },
        select_defaults,
        queue_3_playlist_id="q3",
        state_path=state_path,
    )

    assert [artist.spotify_id for artist in plan.artists] == ["a", "c"]
    assert plan.total_releases == 10
    assert plan.days == 5
    assert plan.open_slots == 0
    assert plan.next_queue == "requeue"
    assert prompted == ["a", "c"]
    assert any(marker.queue == "queue_3" for marker in plan.artists[0].markers)
    assert all(marker.queue != "queue_3" for marker in plan.artists[1].markers)


class MutationSpotify:
    """Record exact playlist marker removals."""

    def __init__(self) -> None:
        self.deletions: list[tuple[str, tuple[str, ...]]] = []

    def _delete(self, path: str, *, payload: dict[str, object]) -> None:
        raw_items = payload["items"]
        assert isinstance(raw_items, list)
        uris = tuple(str(item["uri"]) for item in raw_items)
        self.deletions.append((path, uris))


def test_apply_removes_all_markers_logs_and_advances_priority(tmp_path: Path) -> None:
    selection = discography.ArtistSelection(
        spotify_id="artist",
        name="Artist",
        source_queue="requeue",
        releases=(catalog_release("release"),),
        markers=(
            discography.ArtistMarkers(
                "newfoundland",
                "nf",
                ("spotify:track:nf",),
            ),
            discography.ArtistMarkers(
                "memory_lane",
                "ml",
                ("spotify:track:ml",),
            ),
            discography.ArtistMarkers(
                "queue_3",
                "q3",
                ("spotify:track:q3",),
            ),
        ),
    )
    plan = discography.DiscographyPlan(
        start_queue="requeue",
        next_queue="memory_lane",
        artists=(selection,),
        total_releases=1,
        open_slots=9,
    )
    spotify = MutationSpotify()
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"

    summary = discography.apply_discography_plan(
        spotify,  # type: ignore[arg-type]
        plan,
        state_path=state_path,
        log_path=log_path,
    )

    assert spotify.deletions == [
        ("playlists/nf/items", ("spotify:track:nf",)),
        ("playlists/ml/items", ("spotify:track:ml",)),
        ("playlists/q3/items", ("spotify:track:q3",)),
    ]
    assert summary.removed_artists == 1
    assert summary.removed_markers == 3
    assert summary.next_queue == "memory_lane"
    assert json.loads(state_path.read_text())["next_queue"] == "memory_lane"
    record = json.loads(log_path.read_text())
    assert record["artist_id"] == "artist"
    assert record["releases"][0]["spotify_id"] == "release"
