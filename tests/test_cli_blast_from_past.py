"""Tests for the a-blast-from-the-past CLI command."""

from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_blast_from_the_past_command_defaults_to_ten_and_prints_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    generated_at = datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)
    scrobble = main.blast_from_past.Scrobble(
        track="Selected track",
        artist="Selected artist",
        album="Selected album",
        timestamp_ms=1,
    )
    selection = main.blast_from_past.ScrobbleSelection(
        selected_date=date(2012, 3, 4),
        date_index=42,
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
    batch = main.blast_from_past.BlastFromPastBatch(
        generated_at=generated_at,
        cutoff_date=date(2021, 12, 31),
        available_dates=3698,
        selections=(selection,),
    )

    def add(*_args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return main.blast_from_past.BlastFromPastSpotifySummary(
            playlist_id="blast",
            requested_count=10,
            playlist_length_before=5,
            playlist_length_after=6,
            batch=batch,
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
        lambda: SimpleNamespace(blast_from_the_past_playlist="spotify:playlist:blast"),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main.blast_from_past, "add_blast_from_past_to_spotify", add)

    result = CliRunner().invoke(main.app, ["blast-from-the-past"])

    assert result.exit_code == 0
    assert calls[0]["count"] == 10
    assert calls[0]["max_playlist_length"] is None
    output = result.output
    assert "2026-07-22 13:00:52 UTC" in output
    assert "2012-03-04" in output
    assert "Selected artist" in output
    assert "Selected track" in output
    assert "Selected album" in output
    assert "Playlist: 5 -> 6 items" in output


def test_blast_from_the_past_options_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(
        main.app,
        [
            "blast-from-the-past",
            "--count",
            "3",
            "--max-playlist-length",
            "10",
        ],
    )

    assert result.exit_code != 0
    assert "either --count or --max-playlist-length" in result.output


def test_blast_from_the_past_maximum_does_not_apply_default_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def add(*_args: object, **kwargs: object) -> object:
        received.update(kwargs)
        return main.blast_from_past.BlastFromPastSpotifySummary(
            playlist_id="blast",
            requested_count=0,
            playlist_length_before=10,
            playlist_length_after=10,
            batch=None,
            results=(),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(blast_from_the_past_playlist="blast"),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main.blast_from_past, "add_blast_from_past_to_spotify", add)

    result = CliRunner().invoke(
        main.app,
        ["blast-from-the-past", "--max-playlist-length", "10"],
    )

    assert result.exit_code == 0
    assert received["count"] is None
    assert received["max_playlist_length"] == 10
