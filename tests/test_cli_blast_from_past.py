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
    assert calls[0]["dry_run"] is False
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


def test_blast_from_the_past_artists_command_adds_five_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    result_entry = main.blast_from_past_artists.DormantArtistResult(
        artist="Dormant Artist",
        scrobbles=12,
        spotify_artist="Dormant Artist",
        track="Popular Liked Track",
        popularity=77,
        action="added",
    )

    def add(*_args: object, **kwargs: object) -> object:
        received.update(kwargs)
        return main.blast_from_past_artists.DormantArtistSummary(
            current_year=2026,
            history_years=(2022, 2023, 2024, 2025),
            candidate_count=20,
            represented_count=3,
            playlist_length_before=10,
            playlist_length_after=11,
            requested_count=5,
            results=(result_entry,),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(blast_from_the_past_playlist="blast"),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.blast_from_past_artists,
        "add_dormant_artists_to_blast_from_past",
        add,
    )

    result = CliRunner().invoke(main.app, ["blast-from-the-past-artists"])

    assert result.exit_code == 0
    assert received["count"] == 5
    assert received["dry_run"] is False
    assert "dormant artists" in result.output
    assert "History years: 2022-2025" in result.output
    assert "playlist 10 -> 11" in result.output


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


def test_blast_commands_forward_dry_run(
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
        ["blast-from-the-past", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received["dry_run"] is True
