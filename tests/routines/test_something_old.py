import json
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old


class FakeSpotify:
    def __init__(self, playlist_items: list[dict[str, object]] | None = None) -> None:
        self.playlist_items = playlist_items or []
        self.playlist_calls = 0
        self.posts: list[tuple[str, dict[str, object]]] = []

    def _get(self, path: str, **_kwargs: object) -> dict[str, object]:
        assert path.startswith("playlists/")
        self.playlist_calls += 1
        return {
            "items": list(self.playlist_items),
            "total": len(self.playlist_items),
            "next": None,
        }

    def _post(self, path: str, payload: dict[str, object]) -> None:
        self.posts.append((path, payload))

    def search(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["type"] == "artist"
        return {
            "artists": {
                "items": [
                    {
                        "id": "old-id",
                        "uri": "spotify:artist:old-id",
                        "name": "Old Artist",
                        "popularity": 42,
                        "followers": {"total": 1000},
                    }
                ]
            }
        }

    def artist_top_tracks(self, artist_id: str) -> dict[str, object]:
        assert artist_id == "old-id"
        return {
            "tracks": [
                raw_spotify_track("top-1", "Popular One", "First Album"),
                raw_spotify_track("top-2", "Popular Two", "Second Album"),
            ]
        }


def raw_spotify_track(
    spotify_id: str,
    name: str,
    album: str,
) -> dict[str, object]:
    return {
        "id": spotify_id,
        "uri": f"spotify:track:{spotify_id}",
        "name": name,
        "artists": [{"id": "old-id", "name": "Old Artist"}],
        "album": {"name": album},
        "popularity": 50,
    }


def history_summary(*, dry_run: bool) -> scrobble_history.ScrobbleHistorySummary:
    history = tuple(
        blast_from_past.Scrobble(
            artist="Old Artist",
            track=f"Old Track {index % 10}",
            album="Old Album",
            timestamp_ms=1_000 + index,
        )
        for index in range(50)
    ) + tuple(
        blast_from_past.Scrobble(
            artist="New Artist",
            track=f"New Track {index % 10}",
            album="New Album",
            timestamp_ms=10_000 + index,
        )
        for index in range(50)
    )
    return scrobble_history.ScrobbleHistorySummary(
        checked_at=datetime(2026, 8, 4, tzinfo=UTC),
        username="man-et-arms",
        history=history,
        export_scrobbles=len(history),
        legacy_scrobbles_added=0,
        live_scrobbles_added=0,
        dry_run=dry_run,
        persisted=False,
        backup_path=None,
    )


def patch_history_refresh(
    monkeypatch: pytest.MonkeyPatch,
    received: dict[str, object] | None = None,
) -> None:
    def refresh(*_args: object, **kwargs: object):
        if received is not None:
            received.update(kwargs)
        return history_summary(dry_run=bool(kwargs["dry_run"]))

    monkeypatch.setattr(
        something_old.scrobble_history,
        "refresh_scrobble_history",
        refresh,
    )


def test_golden_oldies_requires_fifty_and_sorts_by_average() -> None:
    summary = history_summary(dry_run=True)
    too_small = tuple(
        blast_from_past.Scrobble("Track", "Small", "", 0) for _ in range(49)
    )

    ranking = something_old.rank_golden_oldies(summary.history + too_small)

    assert [artist.artist for artist in ranking] == ["Old Artist", "New Artist"]
    assert ranking[0].scrobbles == 50
    assert len(ranking[0].top_tracks) == 10
    assert all(track.scrobbles == 5 for track in ranking[0].top_tracks)


def test_nonempty_playlist_stops_before_refresh_or_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify(
        [
            {
                "item": raw_spotify_track(
                    "existing",
                    "Existing",
                    "Existing Album",
                )
            }
        ]
    )
    monkeypatch.setattr(
        something_old.scrobble_history,
        "refresh_scrobble_history",
        lambda *_args, **_kwargs: pytest.fail("history should not refresh"),
    )

    summary = something_old.run_something_old(
        spotify,
        object(),
        "playlist",
        expected_username="man-et-arms",
        mode_reader=lambda *_args: pytest.fail("should not prompt"),
        album_choice_reader=lambda *_args: pytest.fail("should not prompt"),
    )

    assert summary.action == "playlist not empty"
    assert spotify.playlist_calls == 1
    assert spotify.posts == []


def test_dry_run_uses_fresh_oldest_artist_without_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify()
    received: dict[str, object] = {}
    patch_history_refresh(monkeypatch, received)

    summary = something_old.run_something_old(
        spotify,
        object(),
        "playlist",
        expected_username="man-et-arms",
        mode_reader=lambda *_args: "spotify_top_tracks",
        album_choice_reader=lambda *_args: pytest.fail("album prompt is not needed"),
        dry_run=True,
    )

    assert received["dry_run"] is True
    assert summary.action == "would add"
    assert summary.artist is not None
    assert summary.artist.artist == "Old Artist"
    assert [track.track for track in summary.tracks] == ["Popular One", "Popular Two"]
    assert spotify.playlist_calls == 1
    assert spotify.posts == []


def test_real_run_rechecks_empty_playlist_then_logs_exact_addition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spotify = FakeSpotify()
    patch_history_refresh(monkeypatch)
    log_path = tmp_path / "something-old.jsonl"

    summary = something_old.run_something_old(
        spotify,
        object(),
        "playlist",
        expected_username="man-et-arms",
        mode_reader=lambda *_args: "spotify_top_tracks",
        album_choice_reader=lambda *_args: pytest.fail("album prompt is not needed"),
        log_path=log_path,
    )

    assert summary.action == "added"
    assert spotify.playlist_calls == 2
    assert spotify.posts == [
        (
            "playlists/playlist/items",
            {"uris": ["spotify:track:top-1", "spotify:track:top-2"]},
        )
    ]
    audit = json.loads(log_path.read_text(encoding="utf-8"))
    assert audit["artist"]["artist"] == "Old Artist"
    assert [track["track"] for track in audit["tracks"]] == [
        "Popular One",
        "Popular Two",
    ]


def test_real_run_refuses_to_add_if_playlist_fills_during_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class PlaylistFillsSpotify(FakeSpotify):
        def _get(self, path: str, **_kwargs: object) -> dict[str, object]:
            assert path.startswith("playlists/")
            self.playlist_calls += 1
            items = (
                []
                if self.playlist_calls == 1
                else [
                    {
                        "item": raw_spotify_track(
                            "new-existing",
                            "New Existing",
                            "New Existing Album",
                        )
                    }
                ]
            )
            return {"items": items, "total": len(items), "next": None}

    spotify = PlaylistFillsSpotify()
    patch_history_refresh(monkeypatch)
    log_path = tmp_path / "something-old.jsonl"

    with pytest.raises(something_old.SomethingOldError, match="changed"):
        something_old.run_something_old(
            spotify,
            object(),
            "playlist",
            expected_username="man-et-arms",
            mode_reader=lambda *_args: "spotify_top_tracks",
            album_choice_reader=lambda *_args: pytest.fail(
                "album prompt is not needed"
            ),
            log_path=log_path,
        )

    assert spotify.playlist_calls == 2
    assert spotify.posts == []
    assert not log_path.exists()


def test_album_mode_adds_the_complete_chronological_release_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spotify = FakeSpotify()
    patch_history_refresh(monkeypatch)
    release = slow_listening.DiscographyRelease(
        spotify_id="release-id",
        uri="spotify:album:release-id",
        name="Plain EP",
        release_type="EP",
        release_date="2010-01-01",
        chronology_date="2010-01-01",
        total_tracks=2,
        primary_artist_id="old-id",
        primary_artist_name="Old Artist",
        identity="plain ep",
        saved=True,
        plain=True,
        edition_rank=0,
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "load_discography",
        lambda *_args: (release,),
    )
    monkeypatch.setattr(
        something_old.slow_listening,
        "load_release_tracks",
        lambda *_args: (
            something_old.slow_listening.new_wine.ReleaseTrack(
                "track-1", "spotify:track:track-1", "First", 1, 1
            ),
            something_old.slow_listening.new_wine.ReleaseTrack(
                "track-2", "spotify:track:track-2", "Second", 1, 2
            ),
        ),
    )

    summary = something_old.run_something_old(
        spotify,
        object(),
        "playlist",
        expected_username="man-et-arms",
        mode_reader=lambda *_args: "album",
        album_choice_reader=lambda _artist, releases: releases[0].spotify_id,
        dry_run=True,
    )

    assert summary.release == release
    assert [track.track for track in summary.tracks] == ["First", "Second"]


def test_lastfm_top_tracks_use_strict_spotify_matching() -> None:
    class SearchSpotify:
        def search(self, **kwargs: object) -> dict[str, object]:
            query = str(kwargs["q"])
            name = "Most Played" if "Most Played" in query else "Second Played"
            return {"tracks": {"items": [raw_spotify_track(name, name, "Album")]}}

        def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
            return [False] * len(ids)

    artist = something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1000,
        first_scrobble_ms=1,
        last_scrobble_ms=2000,
        top_tracks=(
            something_old.LastFmTrackStat("Most Played", 30, 2000),
            something_old.LastFmTrackStat("Second Played", 20, 1900),
        ),
    )

    tracks = something_old.select_lastfm_top_tracks(
        SearchSpotify(),
        artist,
        lambda operation, _description: operation(),
    )

    assert [track.track for track in tracks] == ["Most Played", "Second Played"]
    assert [track.lastfm_scrobbles for track in tracks] == [30, 20]
