"""Tests for the interactive album-limit review routine."""

import json

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.routines import review_album_limits
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError


def _album(album_id: str = "alb1") -> SimplifiedAlbum:
    return SimplifiedAlbum(
        spotify_id=album_id,
        name="OK Computer",
        artist=SimplifiedArtist(spotify_id="art1", name="Radiohead"),
        ordering_string="OKCOMPUTER",
    )


def _library() -> YourLibraryFile:
    return YourLibraryFile(
        tracks=[],
        albums=[
            YourLibraryAlbum(
                artist="Radiohead", album="OK Computer", uri="spotify:album:alb1"
            )
        ],
        artists=[YourLibraryArtist(name="Radiohead", uri="spotify:artist:art1")],
    )


class FakeSpotify:
    """Small Spotify stand-in for album evaluation and deletion."""

    def __init__(self, rate_limit_on_delete: bool = False) -> None:
        self.deleted: list[list[str]] = []
        self.rate_limit_on_delete = rate_limit_on_delete

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
            ],
            "next": None,
        }

    def current_user_saved_albums_delete(self, albums):
        if self.rate_limit_on_delete:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "120"},
            )
        self.deleted.append(list(albums))


def test_review_removes_album_from_spotify_and_total_file(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[SimplifiedAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify()

    monkeypatch.setattr(review_album_limits, "load_total_albums_file", lambda: albums)
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_file",
        lambda items: saved_albums.append(list(items)),
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "r",
        echo=output.append,
        log_path=log_path,
    )

    assert sp.deleted == [["alb1"]]
    assert saved_albums == [[]]
    log_entry = json.loads(log_path.read_text().strip())
    assert log_entry["spotify_id"] == "alb1"
    assert log_entry["liked_tracks"] == 0
    assert log_entry["total_tracks"] == 2
    assert any(line == "Removed: Radiohead - OK Computer" for line in output)


def test_review_skip_is_only_for_current_run(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[SimplifiedAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify()

    monkeypatch.setattr(review_album_limits, "load_total_albums_file", lambda: albums)
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_file",
        lambda items: saved_albums.append(list(items)),
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "s",
        echo=output.append,
        log_path=log_path,
    )

    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()
    assert any(line == "Skipped: Radiohead - OK Computer" for line in output)


def test_review_exits_cleanly_on_rate_limit_without_saving(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[SimplifiedAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_delete=True)

    monkeypatch.setattr(review_album_limits, "load_total_albums_file", lambda: albums)
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_file",
        lambda items: saved_albums.append(list(items)),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        review_album_limits.review_album_limits(
            sp,
            action_reader=lambda _album, _evaluation: "r",
            echo=lambda _line: None,
            log_path=log_path,
        )

    assert exc.value.retry_after_seconds == 120
    assert saved_albums == []
    assert not log_path.exists()


def test_format_retry_after_rounds_up_to_minutes() -> None:
    assert review_album_limits.format_retry_after(61) == "try again in 2 minutes"
