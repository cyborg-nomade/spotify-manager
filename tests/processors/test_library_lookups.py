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
    assert result.decision == "keep"  # 2/3 >= 0.5
    assert result.source == "files+api"


def test_evaluate_album_by_id() -> None:
    sp = FakeSpotify({"alb2": [{"id": "x", "name": "Bones", "uri": "spotify:track:x"}]})
    result = evaluate_album(sp, album_id="alb2", library=_library())
    assert result.album_id == "alb2"
    assert result.liked_tracks == 0
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
