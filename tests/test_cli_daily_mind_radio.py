"""Tests for the Daily Mind Radio CLI command."""

from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_daily_mind_radio_command_prints_dates_selection_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scrobble = main.blast_from_past.Scrobble(
        track="Selected track",
        artist="Selected artist",
        album="Selected album",
        timestamp_ms=1,
    )
    selection = main.blast_from_past.ScrobbleSelection(
        selected_date=date(2025, 7, 22),
        date_index=0,
        scrobbles_on_date=51,
        page=2,
        total_pages=2,
        direction="bottom up",
        position=3,
        scrobble=scrobble,
    )
    match = main.blast_from_past.SpotifyTrackMatch(
        spotify_id="matched",
        uri="spotify:track:matched",
        track="Selected track - Remastered",
        artists=("Selected artist",),
        album="Selected album (Deluxe)",
        search_rank=2,
        track_similarity=1.0,
        album_similarity=1.0,
        popularity=50,
        liked=True,
    )
    batch = main.daily_mind_radio.DailyMindRadioBatch(
        generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
        target_dates=(date(2025, 7, 22), date(2020, 7, 22)),
        missing_dates=(date(2020, 7, 22),),
        selections=(selection,),
    )
    summary = main.daily_mind_radio.DailyMindRadioSpotifySummary(
        playlist_id="daily",
        batch=batch,
        playlist_length_before=2,
        playlist_length_after=3,
        results=(
            main.blast_from_past.SpotifySelectionResult(
                selection=selection,
                match=match,
                qualifying_matches=2,
                action="added",
            ),
        ),
    )
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(daily_mind_radio_playlist="spotify:playlist:daily"),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(
        main.daily_mind_radio,
        "add_daily_mind_radio_to_spotify",
        lambda *_args, **_kwargs: summary,
    )

    result = CliRunner().invoke(main.app, ["daily-mind-radio"])

    assert result.exit_code == 0
    assert "Anniversary dates: 2025-07-22, 2020-07-22" in result.output
    assert "No scrobbles, skipped: 2020-07-22" in result.output
    assert "2026-07-22 13:00:52 UTC" in result.output
    assert "Selected artist" in result.output
    assert "Selected track" in result.output
    assert "Playlist: 2 -> 3 items" in result.output


def test_daily_mind_radio_command_handles_no_populated_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = main.daily_mind_radio.DailyMindRadioBatch(
        generated_at=None,
        target_dates=(date(2025, 7, 22),),
        missing_dates=(date(2025, 7, 22),),
        selections=(),
    )
    summary = main.daily_mind_radio.DailyMindRadioSpotifySummary(
        playlist_id="daily",
        batch=batch,
        playlist_length_before=None,
        playlist_length_after=None,
        results=(),
    )
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(daily_mind_radio_playlist="daily"),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(
        main.daily_mind_radio,
        "add_daily_mind_radio_to_spotify",
        lambda *_args, **_kwargs: summary,
    )

    result = CliRunner().invoke(main.app, ["daily-mind-radio"])

    assert result.exit_code == 0
    assert "nothing was added" in result.output
