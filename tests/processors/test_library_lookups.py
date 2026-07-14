"""Tests for the files-first artist-stats and album-evaluation lookups."""

import pytest

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.processors.library_lookups import get_artist_library_stats
from spotify_manager.processors.library_lookups import required_liked_tracks


def _library() -> YourLibraryFile:
    return YourLibraryFile(
        tracks=[
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Airbag",
                uri="spotify:track:t1",
            ),
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Karma Police",
                uri="spotify:track:t2",
            ),
            YourLibraryTrack(
                artist="Other", album="Z", track="Q", uri="spotify:track:t9"
            ),
        ],
        albums=[
            YourLibraryAlbum(
                artist="Radiohead", album="OK Computer", uri="spotify:album:alb1"
            ),
            YourLibraryAlbum(
                artist="Radiohead", album="The Bends", uri="spotify:album:alb2"
            ),
        ],
        artists=[YourLibraryArtist(name="Radiohead", uri="spotify:artist:art1")],
    )


class FakeSpotify:
    """Returns a fixed album track list keyed by album id."""

    def __init__(self, tracks_by_album: dict[str, list[dict]]) -> None:
        self._tracks_by_album = tracks_by_album
        self.requested: list[str] = []

    def album_tracks(self, album_id, limit=50, offset=0):
        self.requested.append(album_id)
        return {"items": self._tracks_by_album.get(album_id, []), "next": None}


def test_artist_stats_by_name() -> None:
    stats = get_artist_library_stats(name="radiohead ", library=_library())
    assert stats.artist_id == "art1"
    assert stats.artist_name == "Radiohead"
    assert stats.liked_tracks == 2
    assert stats.saved_releases == 2
    assert stats.source == "files"


def test_artist_stats_by_id_resolves_name() -> None:
    stats = get_artist_library_stats(artist_id="art1", library=_library())
    assert stats.artist_name == "Radiohead"
    assert stats.liked_tracks == 2


def test_artist_stats_unknown_id_raises() -> None:
    with pytest.raises(ArtistNotFoundError):
        get_artist_library_stats(artist_id="nope", library=_library())


def test_evaluate_album_resolves_exact_id_not_search() -> None:
    sp = FakeSpotify(
        {
            "alb1": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
                {"id": "t3", "name": "Let Down", "uri": "spotify:track:t3"},
            ]
        }
    )
    result = evaluate_album(sp, name="ok computer", library=_library())
    assert sp.requested == ["alb1"]  # resolved to the saved album, never searched
    assert result.album_id == "alb1"
    assert result.total_tracks == 3
    assert result.liked_tracks == 2  # t1, t2 liked; t3 not
    assert result.required_liked_tracks == 1
    assert result.decision == "keep"
    assert result.source == "files+api"
    assert [track.spotify_id for track in result.tracks] == ["t1", "t2", "t3"]


def test_evaluate_album_rounds_down_required_likes_for_odd_track_counts() -> None:
    sp = FakeSpotify(
        {
            "alb1": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
                {"id": "t3", "name": "Let Down", "uri": "spotify:track:t3"},
                {"id": "t4", "name": "Exit Music", "uri": "spotify:track:t4"},
                {"id": "t5", "name": "Electioneering", "uri": "spotify:track:t5"},
            ]
        }
    )

    result = evaluate_album(sp, name="ok computer", library=_library())

    assert result.total_tracks == 5
    assert result.liked_tracks == 2
    assert result.liked_ratio == 0.4
    assert result.required_liked_tracks == 2
    assert result.decision == "keep"


def test_required_liked_tracks_keeps_non_empty_positive_threshold_meaningful() -> None:
    assert required_liked_tracks(5, 0.5) == 2
    assert required_liked_tracks(3, 0.5) == 1
    assert required_liked_tracks(1, 0.5) == 1
    assert required_liked_tracks(1, 0) == 0


def test_evaluate_album_by_id() -> None:
    sp = FakeSpotify({"alb2": [{"id": "x", "name": "Bones", "uri": "spotify:track:x"}]})
    result = evaluate_album(sp, album_id="alb2", library=_library())
    assert result.album_id == "alb2"
    assert result.liked_tracks == 0
    assert result.required_liked_tracks == 1
    assert result.decision == "remove"


def test_evaluate_album_ambiguous_name() -> None:
    lib = _library()
    lib.albums.append(
        YourLibraryAlbum(
            artist="Some Tribute Band",
            album="OK Computer",
            uri="spotify:album:dup",
        )
    )
    sp = FakeSpotify({})
    with pytest.raises(AmbiguousAlbumError) as exc:
        evaluate_album(sp, name="OK Computer", library=lib)
    assert len(exc.value.candidates) == 2


def test_evaluate_album_ambiguous_resolved_by_artist() -> None:
    lib = _library()
    lib.albums.append(
        YourLibraryAlbum(
            artist="Some Tribute Band",
            album="OK Computer",
            uri="spotify:album:dup",
        )
    )
    sp = FakeSpotify(
        {"alb1": [{"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"}]}
    )
    result = evaluate_album(sp, name="OK Computer", artist="Radiohead", library=lib)
    assert result.album_id == "alb1"


def test_evaluate_album_name_not_found() -> None:
    with pytest.raises(AlbumNotFoundError):
        evaluate_album(FakeSpotify({}), name="Nonexistent", library=_library())


_ALB1 = {
    "alb1": [
        {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
        {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
        {"id": "t3", "name": "Let Down", "uri": "spotify:track:t3"},
    ]
}


def test_cache_hit_skips_api(album_cache_store: dict) -> None:
    sp = FakeSpotify(_ALB1)
    first = evaluate_album(sp, name="ok computer", library=_library())
    assert first.from_cache is False
    assert first.source == "files+api"
    assert sp.requested == ["alb1"]
    assert "alb1" in album_cache_store  # persisted

    second = evaluate_album(sp, name="ok computer", library=_library())
    assert second.from_cache is True
    assert second.source == "files"
    assert sp.requested == ["alb1"]  # no second API call
    assert second.decision == first.decision == "keep"


def test_refresh_cache_refetches(album_cache_store: dict) -> None:
    sp = FakeSpotify(_ALB1)
    evaluate_album(sp, name="ok computer", library=_library())
    evaluate_album(sp, name="ok computer", library=_library(), refresh_cache=True)
    assert sp.requested == ["alb1", "alb1"]  # forced re-fetch


def test_no_cache_does_not_persist(album_cache_store: dict) -> None:
    sp = FakeSpotify(_ALB1)
    result = evaluate_album(sp, name="ok computer", library=_library(), use_cache=False)
    assert result.from_cache is False
    assert album_cache_store == {}  # nothing written


def test_client_factory_called_only_on_miss(album_cache_store: dict) -> None:
    sp = FakeSpotify(_ALB1)
    calls: list[int] = []

    def factory():
        calls.append(1)
        return sp

    evaluate_album(client_factory=factory, name="ok computer", library=_library())
    assert calls == [1]  # built the client on the miss
    evaluate_album(client_factory=factory, name="ok computer", library=_library())
    assert calls == [1]  # cache hit -> factory never called again
