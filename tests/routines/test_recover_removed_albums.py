"""Tests for removed-album artist auditing and future-release recovery."""

import json
from datetime import date

import pytest

from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines import recover_removed_albums


@pytest.mark.parametrize(
    ("release_date", "precision", "expected"),
    [
        ("2027", "year", True),
        ("2026", "year", False),
        ("2026-08", "month", True),
        ("2026-07", "month", False),
        ("2026-07-15", "day", True),
        ("2026-07-14", "day", False),
        ("not-a-date", "day", False),
    ],
)
def test_release_is_in_future_respects_spotify_date_precision(
    release_date: str,
    precision: str,
    expected: bool,
) -> None:
    assert (
        recover_removed_albums.release_is_in_future(
            release_date,
            precision,
            today=date(2026, 7, 14),
        )
        is expected
    )


def test_load_removed_album_records_deduplicates_ids(tmp_path) -> None:
    log_path = tmp_path / "removed.jsonl"
    entries = [
        {"spotify_id": "album1", "album": "First", "artist": "One"},
        {"spotify_id": "album1", "album": "Duplicate", "artist": "One"},
        {"spotify_id": "album2", "album": "Second", "artist": "Two"},
    ]
    log_path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))

    records = recover_removed_albums.load_removed_album_records(log_path)

    assert [record.spotify_id for record in records] == ["album1", "album2"]
    assert records[0].album == "First"


class FakeSpotify:
    """Spotify stand-in covering the recovery API calls."""

    def __init__(self) -> None:
        self.album_calls: list[list[str]] = []
        self.follow_checks: list[list[str]] = []
        self.followed_batches: list[list[str]] = []
        self.saved_album_checks: list[list[str]] = []
        self.saved_album_batches: list[list[str]] = []
        self.followed_artist_ids = {"primary"}
        self.saved_album_ids: set[str] = set()
        self.album_metadata = {
            "future": {
                "id": "future",
                "uri": "spotify:album:future",
                "name": "Tomorrow's Record",
                "artists": [
                    {"id": "primary", "name": "Primary Artist"},
                    {"id": "guest", "name": "Guest Artist"},
                ],
                "release_date": "2026-08-01",
                "release_date_precision": "day",
            }
        }

    def albums(self, album_ids):
        self.album_calls.append(list(album_ids))
        return {"albums": [self.album_metadata.get(album_id) for album_id in album_ids]}

    def current_user_following_artists(self, artist_ids):
        self.follow_checks.append(list(artist_ids))
        return [artist_id in self.followed_artist_ids for artist_id in artist_ids]

    def user_follow_artists(self, artist_ids):
        self.followed_batches.append(list(artist_ids))
        self.followed_artist_ids.update(artist_ids)

    def current_user_saved_albums_contains(self, album_ids):
        self.saved_album_checks.append(list(album_ids))
        return [album_id in self.saved_album_ids for album_id in album_ids]

    def current_user_saved_albums_add(self, album_ids):
        self.saved_album_batches.append(list(album_ids))
        self.saved_album_ids.update(album_ids)


def _stats_report() -> StatsReport:
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=0,
            removed_albums=0,
            added_albums=0,
            growth=0,
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=1,
            removed_artists=0,
            added_artists=0,
            growth=0,
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=10,
            removed_tracks=0,
            added_tracks=0,
            growth=0,
        ),
        avg_albums_per_artists=0,
        avg_liked_tracks_per_artists=10,
    )


def test_recovery_follows_all_artists_and_restores_future_album(
    monkeypatch,
    tmp_path,
) -> None:
    removal_log_path = tmp_path / "removed.jsonl"
    recovery_log_path = tmp_path / "recovery.jsonl"
    removal_log_path.write_text(
        json.dumps(
            {
                "spotify_id": "future",
                "album": "Tomorrow's Record",
                "artist": "Primary Artist",
            }
        )
        + "\n"
    )

    artists = [
        YourLibraryArtist(
            name="Primary Artist",
            uri="spotify:artist:primary",
        )
    ]
    albums = []
    stats_history = {"2026.07.14": _stats_report()}
    saved_artists: list[list] = []
    saved_albums: list[list] = []

    monkeypatch.setattr(
        recover_removed_albums,
        "load_total_artists_file",
        lambda: list(artists),
    )
    monkeypatch.setattr(
        recover_removed_albums,
        "save_total_artists_file",
        lambda items: saved_artists.append(list(items)),
    )
    monkeypatch.setattr(
        recover_removed_albums,
        "load_total_albums_new_file",
        lambda: list(albums),
    )
    monkeypatch.setattr(
        recover_removed_albums,
        "save_total_albums_new_file",
        lambda items: saved_albums.append(list(items)),
    )
    monkeypatch.setattr(
        recover_removed_albums,
        "load_stats_history_file",
        lambda: dict(stats_history),
    )

    def save_stats(items) -> None:
        stats_history.clear()
        stats_history.update(items)

    monkeypatch.setattr(recover_removed_albums, "save_stats_history", save_stats)
    monkeypatch.setattr(
        recover_removed_albums,
        "current_stats_history_key",
        lambda: "2026.07.14",
    )

    sp = FakeSpotify()
    messages: list[str] = []
    summary = recover_removed_albums.recover_removed_albums(
        sp,
        echo=messages.append,
        removal_log_path=removal_log_path,
        recovery_log_path=recovery_log_path,
        today=date(2026, 7, 14),
        transient_retry_delay_seconds=0,
    )

    assert sp.album_calls == [["future"]]
    assert sp.followed_batches == [["guest"]]
    assert sp.saved_album_batches == [["future"]]
    assert {artist.spotify_id for artist in saved_artists[-1]} == {
        "primary",
        "guest",
    }
    assert [album.spotify_id for album in saved_albums[-1]] == ["future"]
    assert stats_history["2026.07.14"].artists_stats.total_followed_artists == 2
    assert stats_history["2026.07.14"].albums_stats.total_saved_albums == 1
    assert summary.multi_artist_albums == 1
    assert summary.artists_followed == 1
    assert summary.future_releases == 1
    assert summary.albums_restored == 1
    assert any(message.startswith("Multiple credited artists") for message in messages)

    events = [json.loads(line) for line in recovery_log_path.read_text().splitlines()]
    assert {event["event"] for event in events} == {
        "artist_checked",
        "album_processed",
    }

    recover_removed_albums.recover_removed_albums(
        sp,
        echo=messages.append,
        removal_log_path=removal_log_path,
        recovery_log_path=recovery_log_path,
        today=date(2026, 7, 14),
        transient_retry_delay_seconds=0,
    )
    assert sp.album_calls == [["future"]]


def test_dry_run_does_not_mutate_spotify_or_write_recovery_state(
    monkeypatch,
    tmp_path,
) -> None:
    removal_log_path = tmp_path / "removed.jsonl"
    recovery_log_path = tmp_path / "recovery.jsonl"
    removal_log_path.write_text(
        json.dumps(
            {
                "spotify_id": "future",
                "album": "Tomorrow's Record",
                "artist": "Primary Artist",
            }
        )
        + "\n"
    )
    monkeypatch.setattr(recover_removed_albums, "load_total_artists_file", list)
    monkeypatch.setattr(recover_removed_albums, "load_total_albums_new_file", list)

    sp = FakeSpotify()
    summary = recover_removed_albums.recover_removed_albums(
        sp,
        removal_log_path=removal_log_path,
        recovery_log_path=recovery_log_path,
        dry_run=True,
        limit=1,
        today=date(2026, 7, 14),
        transient_retry_delay_seconds=0,
    )

    assert summary.albums_restored == 1
    assert sp.followed_batches == []
    assert sp.saved_album_batches == []
    assert not recovery_log_path.exists()
