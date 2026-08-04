from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def empty_history_summary(
    *,
    dry_run: bool,
) -> main.scrobble_history.ScrobbleHistorySummary:
    return main.scrobble_history.ScrobbleHistorySummary(
        checked_at=datetime(2026, 8, 4, tzinfo=UTC),
        username="man-et-arms",
        history=(),
        export_scrobbles=324_691,
        legacy_scrobbles_added=2,
        live_scrobbles_added=3,
        dry_run=dry_run,
        persisted=False,
        backup_path=None,
    )


def test_update_scrobble_history_dry_run_prints_merge_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def refresh(*_args: object, **kwargs: object):
        received.update(kwargs)
        return empty_history_summary(dry_run=True)

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            lastfm_api_key="key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(main.scrobble_history, "refresh_scrobble_history", refresh)

    result = CliRunner().invoke(
        main.app,
        ["update-scrobble-history", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received["dry_run"] is True
    assert received["expected_username"] == "man-et-arms"
    assert "324,691" in result.output
    assert "+3" in result.output
    assert "canonical history was not changed" in result.output


def test_something_old_dry_run_prompts_for_visible_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    artist = main.something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1_000,
        first_scrobble_ms=1,
        last_scrobble_ms=2_000,
        top_tracks=(),
    )
    spotify_artist = main.something_old.SpotifyArtistCandidate(
        spotify_id="artist-id",
        name="Old Artist",
        uri="spotify:artist:artist-id",
        popularity=50,
        followers=1000,
        search_rank=1,
    )
    track = main.something_old.SelectedTrack(
        spotify_id="track-id",
        uri="spotify:track:track-id",
        track="Old Track",
        album="Old Album",
        artists=("Old Artist",),
        source="Last.fm top tracks",
        lastfm_scrobbles=25,
    )

    def run(*_args: object, **kwargs: object):
        received["dry_run"] = kwargs["dry_run"]
        received["mode"] = kwargs["mode_reader"](artist, spotify_artist)
        return main.something_old.SomethingOldSummary(
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            playlist_id="playlist",
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=True,
            action="would add",
            history_refresh=empty_history_summary(dry_run=True),
            ranking_preview=(artist,),
            artist=artist,
            spotify_artist=spotify_artist,
            mode="lastfm_top_tracks",
            release=None,
            tracks=(track,),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            something_old_new_playlist="spotify:playlist:playlist",
            lastfm_api_key="key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main.something_old, "run_something_old", run)

    result = CliRunner().invoke(
        main.app,
        ["something-old", "--dry-run"],
        input="1\n",
    )

    assert result.exit_code == 0
    assert received == {"dry_run": True, "mode": "lastfm_top_tracks"}
    assert "Something Old selection" in result.output
    assert "Old Artist" in result.output
    assert "would add 1 track" in result.output
    assert "local files were unchanged" in result.output
