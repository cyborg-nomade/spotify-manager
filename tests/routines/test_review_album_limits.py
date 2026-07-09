"""Tests for the interactive album-limit review routine."""

import json

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
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


def _stats_report(
    total_followed_artists: int = 10,
    added_artists: int = 0,
    removed_artists: int = 0,
) -> StatsReport:
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=100,
            removed_albums=0,
            added_albums=0,
            growth=0,
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=total_followed_artists,
            removed_artists=removed_artists,
            added_artists=added_artists,
            growth=0,
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=50,
            removed_tracks=0,
            added_tracks=0,
            growth=0,
        ),
        avg_albums_per_artists=100 // total_followed_artists,
        avg_liked_tracks_per_artists=50 // total_followed_artists,
    )


@pytest.fixture(autouse=True)
def artist_persistence_store(monkeypatch, tmp_path) -> dict:
    artists: list[YourLibraryArtist] = []
    stats_key = review_album_limits.current_stats_history_key()
    stats_history = {stats_key: _stats_report()}
    saved_artists: list[list[YourLibraryArtist]] = []
    saved_stats_history: list[dict[str, StatsReport]] = []

    def load_artists() -> list[YourLibraryArtist]:
        return list(artists)

    def save_artists(items: list[YourLibraryArtist]) -> None:
        artists.clear()
        artists.extend(items)
        saved_artists.append(list(items))

    def load_stats_history() -> dict[str, StatsReport]:
        return dict(stats_history)

    def save_stats_history(items: dict[str, StatsReport]) -> None:
        stats_history.clear()
        stats_history.update(items)
        saved_stats_history.append(dict(items))

    monkeypatch.setattr(review_album_limits, "load_total_artists_file", load_artists)
    monkeypatch.setattr(review_album_limits, "save_total_artists_file", save_artists)
    monkeypatch.setattr(
        review_album_limits, "load_stats_history_file", load_stats_history
    )
    monkeypatch.setattr(review_album_limits, "save_stats_history", save_stats_history)
    monkeypatch.setattr(
        review_album_limits,
        "REVIEW_DECISIONS_PATH",
        tmp_path / "review_album_limits_decisions.json",
    )

    return {
        "artists": artists,
        "stats_history": stats_history,
        "saved_artists": saved_artists,
        "saved_stats_history": saved_stats_history,
        "stats_key": stats_key,
    }


class FakeSpotify:
    """Small Spotify stand-in for album evaluation and deletion."""

    def __init__(
        self,
        rate_limit_on_delete: bool = False,
        rate_limit_on_follow_check: bool = False,
        rate_limit_on_album_metadata: bool = False,
        rate_limit_on_saved_track_check: bool = False,
        followed_artists: set[str] | None = None,
        saved_tracks: set[str] | None = None,
        album_tracks: list[dict] | None = None,
    ) -> None:
        self.deleted: list[list[str]] = []
        self.follow_checks: list[list[str]] = []
        self.followed: list[list[str]] = []
        self.album_metadata_calls: list[str] = []
        self.saved_track_checks: list[list[str]] = []
        self.rate_limit_on_delete = rate_limit_on_delete
        self.rate_limit_on_follow_check = rate_limit_on_follow_check
        self.rate_limit_on_album_metadata = rate_limit_on_album_metadata
        self.rate_limit_on_saved_track_check = rate_limit_on_saved_track_check
        self.followed_artists = set(followed_artists or set())
        self.saved_tracks = set(saved_tracks or set())
        self._album_tracks = album_tracks or [
            {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
            {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
        ]

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": self._album_tracks,
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

    def current_user_saved_tracks_contains(self, tracks):
        if self.rate_limit_on_saved_track_check:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "90"},
            )
        self.saved_track_checks.append(list(tracks))
        return [track in self.saved_tracks for track in tracks]

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
    sp = FakeSpotify(saved_tracks={"t1"})

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
    assert sp.saved_track_checks == [["t1", "t2"]]
    assert saved_albums == [[]]
    log_entry = json.loads(log_path.read_text().strip())
    assert log_entry["action"] == "manual"
    assert log_entry["spotify_id"] == "alb1"
    assert log_entry["liked_tracks"] == 0
    assert log_entry["live_liked_tracks"] == 1
    assert log_entry["total_tracks"] == 2
    assert any(line == "Removed: OK Computer - Radiohead" for line in output)


def test_review_auto_removes_album_with_zero_live_liked_tracks(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks=set())

    def fail_action_reader(_album, _evaluation):
        raise AssertionError("zero-live-like albums should not prompt")

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
        action_reader=fail_action_reader,
        echo=output.append,
        log_path=log_path,
    )

    assert sp.saved_track_checks == [["t1", "t2"]]
    assert sp.deleted == [["alb1"]]
    assert saved_albums == [[]]
    log_entry = json.loads(log_path.read_text().strip())
    assert log_entry["action"] == "auto_zero_live_likes"
    assert log_entry["live_liked_tracks"] == 0
    assert any(
        line == "Auto-removed (0 live liked tracks): OK Computer - Radiohead"
        for line in output
    )


def test_review_prompts_when_live_liked_tracks_exist(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks={"t2"})

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

    assert sp.saved_track_checks == [["t1", "t2"]]
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()
    assert any(line == "Live liked tracks: 1" for line in output)
    assert any(line == "Skipped: OK Computer - Radiohead" for line in output)


def test_live_liked_track_checks_are_batched_for_large_albums(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    output: list[str] = []
    album_tracks = [
        {
            "id": f"t{index}",
            "name": f"Track {index}",
            "uri": f"spotify:track:t{index}",
        }
        for index in range(45)
    ]
    sp = FakeSpotify(album_tracks=album_tracks, saved_tracks={"t44"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)

    review_album_limits.review_album_limits(
        sp,
        action_reader=lambda _album, _evaluation: "s",
        echo=output.append,
        log_path=tmp_path / "removed_albums_log.jsonl",
    )

    assert [len(batch) for batch in sp.saved_track_checks] == [20, 20, 5]
    assert sp.saved_track_checks[-1] == ["t40", "t41", "t42", "t43", "t44"]
    assert sp.deleted == []
    assert any(line == "Live liked tracks: 1" for line in output)


def test_keep_decision_persists_between_review_runs(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    decisions_path = tmp_path / "review_decisions.json"
    first_output: list[str] = []
    second_output: list[str] = []
    first_sp = FakeSpotify(saved_tracks={"t1"})
    second_sp = FakeSpotify(saved_tracks={"t1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", lambda: albums
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)

    review_album_limits.review_album_limits(
        first_sp,
        action_reader=lambda _album, _evaluation: "k",
        echo=first_output.append,
        log_path=tmp_path / "removed_albums_log.jsonl",
        decisions_path=decisions_path,
    )

    def fail_action_reader(_album, _evaluation):
        raise AssertionError("persisted keep decisions should not prompt again")

    review_album_limits.review_album_limits(
        second_sp,
        action_reader=fail_action_reader,
        echo=second_output.append,
        log_path=tmp_path / "removed_albums_log.jsonl",
        decisions_path=decisions_path,
    )

    decisions = json.loads(decisions_path.read_text())
    assert decisions["alb1"]["decision"] == "keep"
    assert first_sp.saved_track_checks == [["t1", "t2"]]
    assert first_sp.deleted == []
    assert any(line == "Kept anyway: OK Computer - Radiohead" for line in first_output)
    assert second_sp.follow_checks == []
    assert second_sp.saved_track_checks == []
    assert any(
        line == "[1/1] previously kept: OK Computer - Radiohead"
        for line in second_output
    )


def test_review_records_followed_artist_and_updates_stats_history(
    monkeypatch, tmp_path, artist_persistence_store
) -> None:
    albums = [_album()]
    sp = FakeSpotify()

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

    saved_artists = artist_persistence_store["saved_artists"]
    saved_stats_history = artist_persistence_store["saved_stats_history"]
    stats_key = artist_persistence_store["stats_key"]

    assert [[artist.spotify_id for artist in items] for items in saved_artists] == [
        ["art1"]
    ]
    report = saved_stats_history[-1][stats_key]
    assert report.artists_stats.total_followed_artists == 11
    assert report.artists_stats.added_artists == 1
    assert report.artists_stats.growth == 10
    assert report.avg_albums_per_artists == 9
    assert report.avg_liked_tracks_per_artists == 4


def test_enter_defaults_to_remove_for_remove_candidate(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    sp = FakeSpotify(saved_tracks={"t1"})

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
        action_reader=lambda _album, _evaluation: "",
        echo=lambda _line: None,
        log_path=tmp_path / "removed_albums_log.jsonl",
    )

    assert sp.deleted == [["alb1"]]
    assert saved_albums == [[]]


def test_review_reports_progress_after_each_completed_album(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    progress_updates: list[tuple[int, int]] = []
    sp = FakeSpotify()

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
        progress_callback=lambda position, total: progress_updates.append(
            (position, total)
        ),
    )

    assert progress_updates == [(1, 1)]


def test_review_skip_is_only_for_current_run(monkeypatch, tmp_path) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks={"t1"})

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
    assert any(line == "Skipped: OK Computer - Radiohead" for line in output)


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
    assert any("keep: OK Computer - Radiohead" in line for line in output)


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


def test_review_exits_cleanly_on_live_liked_track_rate_limit(
    monkeypatch, tmp_path
) -> None:
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_saved_track_check=True)

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

    assert exc.value.retry_after_seconds == 90
    assert sp.deleted == []
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
