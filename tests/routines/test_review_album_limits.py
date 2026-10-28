"""Tests for the interactive album-limit review routine."""

import json
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import partial
from pathlib import Path
from typing import Any
from typing import Never
from typing import TypedDict
from unittest.mock import Mock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException

from spotify_manager import loaders_savers as file_boundaries
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
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
from tests.support.framework_stubs import snapshot_items
from tests.support.runtime_resources import Answer
from tests.support.runtime_resources import CountEvents
from tests.support.runtime_resources import DelayList
from tests.support.runtime_resources import DiscardMessages
from tests.support.runtime_resources import MessageList
from tests.support.runtime_resources import NoWait


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
    monkeypatch.setattr(
        file_boundaries,
        "load_total_artists_file",
        review_album_limits.load_total_artists_file,
    )
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
        transient_failures_on_follow_check: int = 0,
        followed_artists: set[str] | None = None,
        saved_tracks: set[str] | None = None,
        album_tracks: list[dict] | None = None,
    ) -> None:
        self.deleted: list[list[str]] = []
        self.follow_checks: list[list[str]] = []
        self.follow_check_attempts: list[list[str]] = []
        self.followed: list[list[str]] = []
        self.album_metadata_calls: list[str] = []
        self.saved_track_checks: list[list[str]] = []
        self.rate_limit_on_delete = rate_limit_on_delete
        self.rate_limit_on_follow_check = rate_limit_on_follow_check
        self.rate_limit_on_album_metadata = rate_limit_on_album_metadata
        self.rate_limit_on_saved_track_check = rate_limit_on_saved_track_check
        self.transient_failures_on_follow_check = transient_failures_on_follow_check
        self.followed_artists = set(followed_artists or set())
        self.saved_tracks = set(saved_tracks or set())
        self._album_tracks = album_tracks or [
            {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
            {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
        ]

    async def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": self._album_tracks,
            "next": None,
        }

    async def album(self, album_id):
        if self.rate_limit_on_album_metadata:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "240"},
            )
        self.album_metadata_calls.append(album_id)
        return {"artists": [{"id": "art1", "name": "Radiohead"}]}

    async def current_user_following_artists(self, artists):
        self.follow_check_attempts.append(list(artists))
        if self.transient_failures_on_follow_check > 0:
            self.transient_failures_on_follow_check -= 1
            raise SpotifyException(
                503,
                -1,
                "upstream connect error or disconnect/reset before headers",
            )
        if self.rate_limit_on_follow_check:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "180"},
            )
        self.follow_checks.append(list(artists))
        return [artist in self.followed_artists for artist in artists]

    async def user_follow_artists(self, artists):
        self.followed.append(list(artists))
        self.followed_artists.update(artists)

    async def current_user_saved_tracks_contains(self, tracks):
        if self.rate_limit_on_saved_track_check:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "90"},
            )
        self.saved_track_checks.append(list(tracks))
        return [track in self.saved_tracks for track in tracks]

    async def current_user_saved_albums_delete(self, albums):
        if self.rate_limit_on_delete:
            raise SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "120"},
            )
        self.deleted.append(list(albums))


async def test_review_removes_album_from_spotify_and_total_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review removes album from spotify and total file.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks={"t1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("r"),
            echo=MessageList(output),
            log_path=log_path,
        )
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


async def test_review_auto_removes_album_with_zero_live_liked_tracks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review auto removes album with zero live liked tracks.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks=set())
    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )
    scenario = ReviewAutoRemovesAlbumWithZeroLiveLikedTracksScenario()
    (
        review_album_limits.review_album_limits(
            sp, action_reader=scenario, echo=MessageList(output), log_path=log_path
        )
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


async def test_review_prompts_when_live_liked_tracks_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review prompts when live liked tracks exist.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks={"t2"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=MessageList(output),
            log_path=log_path,
        )
    )

    assert sp.saved_track_checks == [["t1", "t2"]]
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()
    assert any(line == "Live liked tracks: 1" for line in output)
    assert any(line == "Skipped: OK Computer - Radiohead" for line in output)


async def test_live_liked_track_checks_are_batched_for_large_albums(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Live liked track checks are batched for large albums.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
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
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=MessageList(output),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
    )

    assert [len(batch) for batch in sp.saved_track_checks] == [20, 20, 5]
    assert sp.saved_track_checks[-1] == ["t40", "t41", "t42", "t43", "t44"]
    assert sp.deleted == []
    assert any(line == "Live liked tracks: 1" for line in output)


async def test_keep_decision_persists_between_review_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep decision persists between review runs.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    decisions_path = tmp_path / "review_decisions.json"
    first_output: list[str] = []
    second_output: list[str] = []
    first_sp = FakeSpotify(saved_tracks={"t1"})
    second_sp = FakeSpotify(saved_tracks={"t1"})
    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    (
        review_album_limits.review_album_limits(
            first_sp,
            action_reader=Answer("k"),
            echo=MessageList(first_output),
            log_path=tmp_path / "removed_albums_log.jsonl",
            decisions_path=decisions_path,
        )
    )
    scenario = KeepDecisionPersistsBetweenReviewRunsScenario()
    (
        review_album_limits.review_album_limits(
            second_sp,
            action_reader=scenario,
            echo=MessageList(second_output),
            log_path=tmp_path / "removed_albums_log.jsonl",
            decisions_path=decisions_path,
        )
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


async def test_review_retries_transient_spotify_server_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review retries transient spotify server errors.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    output: list[str] = []
    sleeps: list[float] = []
    sp = FakeSpotify(
        transient_failures_on_follow_check=1,
        followed_artists={"art1"},
    )

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=MessageList(output),
            log_path=tmp_path / "removed_albums_log.jsonl",
            sleep=DelayList(sleeps),
            transient_retry_delay_seconds=123,
        )
    )

    assert sleeps == [123]
    assert sp.follow_check_attempts == [["art1"], ["art1"]]
    assert any(
        line.startswith(
            "Spotify API temporarily unavailable (503) while "
            "checking/following artist for OK Computer - Radiohead. "
            "Retrying in 3 minutes"
        )
        for line in output
    )
    assert any("keep: OK Computer - Radiohead" in line for line in output)


async def test_review_stops_cleanly_after_transient_spotify_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review stops cleanly after transient spotify retries are exhausted.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    sleeps: list[float] = []
    sp = FakeSpotify(transient_failures_on_follow_check=2)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    with pytest.raises(review_album_limits.SpotifyTransientServerError) as exc:
        (
            review_album_limits.review_album_limits(
                sp,
                action_reader=Answer("s"),
                echo=DiscardMessages(),
                log_path=tmp_path / "removed_albums_log.jsonl",
                sleep=DelayList(sleeps),
                transient_retry_delay_seconds=7,
                transient_max_attempts=2,
            )
        )

    assert exc.value.http_status == 503
    assert (
        exc.value.operation == "checking/following artist for OK Computer - Radiohead"
    )
    assert exc.value.attempts == 2
    assert sleeps == [7]


@pytest.mark.parametrize(
    "error",
    [
        RequestsConnectionError(
            "Connection aborted.",
            ConnectionResetError(104, "Connection reset by peer"),
        ),
        RequestsTimeout("Spotify request timed out"),
    ],
)
async def test_retry_spotify_server_errors_retries_transport_failures(
    error: RequestsConnectionError | RequestsTimeout,
) -> None:
    """Retry spotify server errors retries transport failures.

    Args:
        error: Original error.
    """
    output: list[str] = []
    sleeps: list[float] = []
    request = TransportRequest(error)
    retry = SpotifyRetries(MessageList(output), DelayList(sleeps), 10, 3)
    result = await _send(retry, request)

    assert result == "connected"
    assert request.calls == 2
    assert sleeps == [10]
    assert len(output) == 1
    assert output[0].startswith(
        "Spotify connection interrupted while loading the Slow Listening "
        "playlist. Retrying in 10 seconds (at "
    )


async def test_retry_spotify_server_errors_reports_exhausted_connection_retries() -> (
    None
):
    """Retry spotify server errors reports exhausted connection retries."""
    request = TransportRequest(
        RequestsConnectionError("Connection reset by peer"), fail_always=True
    )
    retry = SpotifyRetries(DiscardMessages(), NoWait(), 10, 3)
    with pytest.raises(review_album_limits.SpotifyTransientServerError) as exc:
        await _send(retry, request)

    assert request.calls == 3
    assert exc.value.http_status is None
    assert exc.value.attempts == 3
    assert review_album_limits.format_transient_spotify_failure(exc.value) == (
        "Spotify connection remained unavailable after 3 attempts while "
        "loading the Slow Listening playlist"
    )


async def test_review_records_followed_artist_and_updates_stats_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artist_persistence_store: ArtistPublicationObservations,
) -> None:
    """Review records followed artist and updates stats history.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
        artist_persistence_store: Original artist publication and cache observations.
    """
    albums = [_album()]
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=DiscardMessages(),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
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


async def test_enter_defaults_to_remove_for_remove_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Enter defaults to remove for remove candidate.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    sp = FakeSpotify(saved_tracks={"t1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer(""),
            echo=DiscardMessages(),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
    )

    assert sp.deleted == [["alb1"]]
    assert saved_albums == [[]]


async def test_review_reports_progress_after_each_completed_album(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review reports progress after each completed album.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    progress_updates: list[tuple[int, int]] = []
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=DiscardMessages(),
            log_path=tmp_path / "removed_albums_log.jsonl",
            progress_callback=CountEvents(progress_updates),
        )
    )

    assert progress_updates == [(1, 1)]


async def test_review_skip_is_only_for_current_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review skip is only for current run.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    output: list[str] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(saved_tracks={"t1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=MessageList(output),
            log_path=log_path,
        )
    )

    assert sp.deleted == []
    assert sp.followed == [["art1"]]
    assert saved_albums == []
    assert not log_path.exists()
    assert any(line == "Skipped: OK Computer - Radiohead" for line in output)


async def test_review_follows_artist_for_kept_album_without_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review follows artist for kept album without prompt.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    output: list[str] = []
    sp = FakeSpotify()
    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits, "load_your_library_file", Mock(return_value=_library(True))
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    scenario = ReviewFollowsArtistForKeptAlbumWithoutPromptScenario()
    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=scenario,
            echo=MessageList(output),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
    )
    assert sp.deleted == []
    assert sp.followed == [["art1"]]
    assert any("keep: OK Computer - Radiohead" in line for line in output)


async def test_review_does_not_refollow_artist_already_followed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review does not refollow artist already followed.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    sp = FakeSpotify(followed_artists={"art1"})

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=DiscardMessages(),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
    )

    assert sp.follow_checks == [["art1"]]
    assert sp.followed == []


async def test_review_resolves_unfollowed_artist_from_album_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review resolves unfollowed artist from album metadata.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    sp = FakeSpotify()

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True, include_artist=False)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )

    (
        review_album_limits.review_album_limits(
            sp,
            action_reader=Answer("s"),
            echo=DiscardMessages(),
            log_path=tmp_path / "removed_albums_log.jsonl",
        )
    )

    assert sp.album_metadata_calls == ["alb1"]
    assert sp.follow_checks == [["art1"]]
    assert sp.followed == [["art1"]]


async def test_review_exits_cleanly_on_album_metadata_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review exits cleanly on album metadata rate limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_album_metadata=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "load_your_library_file",
        Mock(return_value=_library(True, include_artist=False)),
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        (
            review_album_limits.review_album_limits(
                sp,
                action_reader=Answer("r"),
                echo=DiscardMessages(),
                log_path=log_path,
            )
        )

    assert exc.value.retry_after_seconds == 240
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()


async def test_review_exits_cleanly_on_rate_limit_without_saving(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review exits cleanly on rate limit without saving.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_delete=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        (
            review_album_limits.review_album_limits(
                sp,
                action_reader=Answer("r"),
                echo=DiscardMessages(),
                log_path=log_path,
            )
        )

    assert exc.value.retry_after_seconds == 120
    assert saved_albums == []
    assert not log_path.exists()


async def test_review_exits_cleanly_on_live_liked_track_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review exits cleanly on live liked track rate limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_saved_track_check=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        (
            review_album_limits.review_album_limits(
                sp,
                action_reader=Answer("r"),
                echo=DiscardMessages(),
                log_path=log_path,
            )
        )

    assert exc.value.retry_after_seconds == 90
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()


async def test_review_exits_cleanly_on_follow_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review exits cleanly on follow rate limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        tmp_path: Isolated original fixture storage.
    """
    albums = [_album()]
    saved_albums: list[list[YourLibraryAlbum]] = []
    log_path = tmp_path / "removed_albums_log.jsonl"
    sp = FakeSpotify(rate_limit_on_follow_check=True)

    monkeypatch.setattr(
        review_album_limits, "load_total_albums_new_file", Mock(return_value=albums)
    )
    monkeypatch.setattr(
        file_boundaries,
        "load_total_albums_new_file",
        review_album_limits.load_total_albums_new_file,
    )
    monkeypatch.setattr(review_album_limits, "load_your_library_file", _library)
    monkeypatch.setattr(
        file_boundaries,
        "load_your_library_file",
        review_album_limits.load_your_library_file,
    )
    monkeypatch.setattr(
        review_album_limits,
        "save_total_albums_new_file",
        partial(snapshot_items, saved_albums),
    )

    with pytest.raises(SpotifyRateLimitError) as exc:
        (
            review_album_limits.review_album_limits(
                sp,
                action_reader=Answer("r"),
                echo=DiscardMessages(),
                log_path=log_path,
            )
        )

    assert exc.value.retry_after_seconds == 180
    assert sp.deleted == []
    assert saved_albums == []
    assert not log_path.exists()


def test_format_retry_after_rounds_up_to_minutes() -> None:
    now = datetime(2026, 7, 9, 10, 30, tzinfo=timezone(timedelta(hours=2)))

    assert (
        review_album_limits.format_retry_after(61, now=now)
        == "try again in 2 minutes (at 2026-07-09T10:31:01+02:00)"
    )


def test_retry_after_seconds_parses_spotipy_retry_reason() -> None:
    exc = SpotifyException(
        429,
        -1,
        "/v1/me/library/albums:\n Max Retries",
        reason=(
            "Your application has reached a rate/request limit. "
            "Retry will occur after: 20484 s"
        ),
    )

    assert review_album_limits.get_retry_after_seconds(exc) == 20484


@dataclass
class TransportRequest:
    """Keep original transient transport failures and accepted attempt counts.

    Args:
        error: Original connection or timeout failure.
        fail_always: Whether the original request always fails.
        calls: Original attempt count.
    """

    error: RequestsConnectionError | RequestsTimeout
    fail_always: bool = False
    calls: int = 0

    def send(self) -> str:
        """Execute the original scripted transport request.

        Returns:
            Original accepted connection result.

        Raises:
            RequestsConnectionError: Original scripted connection failure.
            RequestsTimeout: Original scripted timeout.
        """
        self.calls += 1
        if self.fail_always or self.calls == 1:
            raise self.error
        return "connected"


async def _send(retry: SpotifyRetries, request: TransportRequest) -> str:
    for attempt in retry.attempts("loading the Slow Listening playlist"):
        async with attempt:
            response = request.send()
    return response


@dataclass
class ReviewAutoRemovesAlbumWithZeroLiveLikedTracksScenario:
    """Retain the original review auto removes album with zero live liked tracks
    fixture.
    """

    async def choose_action(self, _album: Any, _evaluation: Any) -> Never:
        """Execute the original fail action reader mock boundary.

        Args:
            _album: Original external mock argument.
            _evaluation: Original external mock argument.

        Returns:
            Original fixture result.
        """
        raise AssertionError("zero-live-like albums should not prompt")


@dataclass
class KeepDecisionPersistsBetweenReviewRunsScenario:
    """Retain the original keep decision persists between review runs fixture."""

    async def choose_action(self, _album: Any, _evaluation: Any) -> Never:
        """Execute the original fail action reader mock boundary.

        Args:
            _album: Original external mock argument.
            _evaluation: Original external mock argument.

        Returns:
            Original fixture result.
        """
        raise AssertionError("persisted keep decisions should not prompt again")


@dataclass
class ReviewFollowsArtistForKeptAlbumWithoutPromptScenario:
    """Reject any unexpected prompt for a kept album."""

    async def choose_action(self, _album: Any, _evaluation: Any) -> Never:
        """Execute the original fail action reader mock boundary.

        Args:
            _album: Original external mock argument.
            _evaluation: Original external mock argument.

        Returns:
            Original fixture result.
        """
        raise AssertionError("kept albums should not prompt for removal")


class ArtistPublicationObservations(TypedDict):
    """Describe the original artist publication fixture's stored observations."""

    artists: list[YourLibraryArtist]
    stats_history: dict[str, StatsReport]
    saved_artists: list[list[YourLibraryArtist]]
    saved_stats_history: list[dict[str, StatsReport]]
    stats_key: str
