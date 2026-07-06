"""Tests for the interactive album-limit review routine."""

import json

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import review_album_limits
from spotify_manager.routines.review_album_limits import SpotifyRateLimitError


def _album(album_id: str = "alb1") -> YourLibraryAlbum:
    return YourLibraryAlbum(
        artist="Radiohead",
        album="OK Computer",
        uri=f"spotify:album:{album_id}",
    )


def _library(
    liked_tracks: bool = False, include_artist: bool = True
) -> YourLibraryFile:
    tracks = []
    if liked_tracks:
        tracks = [
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
        ]

    return YourLibraryFile(
        tracks=tracks,
        albums=[
            YourLibraryAlbum(
                artist="Radiohead", album="OK Computer", uri="spotify:album:alb1"
            )
        ],
        artists=[YourLibraryArtist(name="Radiohead", uri="spotify:artist:art1")]
        if include_artist
        else [],
    )


class FakeSpotify:
    """Small Spotify stand-in for album evaluation and deletion."""

    def __init__(
        self,
        rate_limit_on_delete: bool = False,
        rate_limit_on_follow_check: bool = False,
        rate_limit_on_album_metadata: bool = False,
        followed_artists: set[str] | None = None,
    ) -> None:
        self.deleted: list[list[str]] = []
        self.follow_checks: list[list[str]] = []
        self.followed: list[list[str]] = []
        self.album_metadata_calls: list[str] = []
        self.rate_limit_on_delete = rate_limit_on_delete
        self.rate_limit_on_follow_check = rate_limit_on_follow_check
        self.rate_limit_on_album_metadata = rate_limit_on_album_metadata
        self.followed_artists = set(followed_artists or set())

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
            ],
            "next": None,
        }

    def album(self, album_id):
        if self.rate_limit_on_album_metadata:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "240"},
            )
        self.album_metadata_calls.append(album_id)
        return {"artists": [{"id": "art1", "name": "Radiohead"}]}

    def current_user_following_artists(self, artists):
        if self.rate_limit_on_follow_check:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "180"},
            )
        self.follow_checks.append(list(artists))
        return [artist in self.followed_artists for artist in artists]

    def user_follow_artists(self, artists):
        self.followed.append(list(artists))
        self.followed_artists.update(artists)

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
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "r",
        echo=output.append,
        log_path=log_path,
    )

    assert sp.deleted == [["alb1"]]
    assert sp.follow_checks == [["art1"]]
    assert sp.followed == [["art1"]]
    assert sp.album_metadata_calls == []
    assert saved_albums == [[]]
    log_entry = json.loads(log_path.read_text().strip())
    assert log_entry["spotify_id"] == "alb1"
    assert log_entry["liked_tracks"] == 0
    assert log_entry["total_tracks"] == 2
    assert any(line == "Removed: Radiohead - OK Computer" for line in output)


def test_review_skip_is_only_for_current_run(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "s",
        echo=output.append,
        log_path=log_path,
    )

    assert sp.deleted == []
    assert sp.followed == [["art1"]]
    assert saved_albums == []
    assert not log_path.exists()
    assert any(line == "Skipped: Radiohead - OK Computer" for line in output)


def test_review_follows_artist_for_kept_album_without_prompt(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    output: list[str] = []
    sp = FakeSpotify()

    def fail_action_reader(_album, _evaluation):
        raise AssertionError("kept albums should not prompt for removal")

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(
        review_album_limits, "load_your_library_file", lambda: _library(True)
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=fail_action_reader,
        echo=output.append,
        log_path=tmp_path / "removed_albums_log.jsonl",
    )

    assert sp.deleted == []
    assert sp.followed == [["art1"]]
    assert any("keep: Radiohead - OK Computer" in line for line in output)


def test_review_does_not_refollow_artist_already_followed(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    sp = FakeSpotify(followed_artists={"art1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(
        review_album_limits, "load_your_library_file", lambda: _library(True)
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "s",
        echo=lambda _line: None,
        log_path=tmp_path / "removed_albums_log.jsonl",
    )

    assert sp.follow_checks == [["art1"]]
    assert sp.followed == []


def test_review_resolves_unfollowed_artist_from_album_metadata(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        lambda: _library(True, include_artist=False),
    )

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "s",
        echo=lambda _line: None,
        log_path=tmp_path / "removed_albums_log.jsonl",
    )

    assert sp.album_metadata_calls == ["alb1"]
    assert sp.follow_checks == [["art1"]]
    assert sp.followed == [["art1"]]


def test_review_exits_cleanly_on_album_metadata_rate_limit(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_album_metadata=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        lambda: _library(True, include_artist=False),
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        review_album_limits.review_album_limits(
            sp,
            action_reader=lambda _album, _evaluation: "r",
            echo=lambda _line: None,
            log_path=log_path,
        )

    assert exc.value.retry_after_seconds == 240
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()


def test_review_exits_cleanly_on_rate_limit_without_saving(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_delete=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
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


def test_review_exits_cleanly_on_follow_rate_limit(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_follow_check=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        review_album_limits.review_album_limits(
            sp,
            action_reader=lambda _album, _evaluation: "r",
            echo=lambda _line: None,
            log_path=log_path,
        )

    assert exc.value.retry_after_seconds == 180
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()


def test_format_retry_after_rounds_up_to_minutes() -> None:
    assert review_album_limits.format_retry_after(61) == "try again in 2 minutes"
