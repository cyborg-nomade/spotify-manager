"""Tests for the Found Art CLI command."""

from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_found_art_dry_run_defaults_to_twenty_and_prints_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}
    candidate = main.found_art.FoundArtCandidate(
        artist="New Artist",
        track="New Track",
        key=("newartist", "newtrack"),
        score=1.25,
        best_match=0.9,
        supporting_seeds=("Seed Artist - Seed Track",),
    )
    match = main.blast_from_past.SpotifyTrackMatch(
        spotify_id="spotify-id",
        uri="spotify:track:spotify-id",
        track="New Track",
        artists=("New Artist",),
        album="New Album",
        search_rank=1,
        track_similarity=1.0,
        album_similarity=None,
        popularity=50,
    )
    recommendation_seed = main.found_art.FoundArtSeed(
        artist="Seed Artist",
        track="Seed Track",
        key=("seedartist", "seedtrack"),
        source="recent",
        play_count=10,
        source_play_count=5,
        weight=1.0,
    )

    def run(*_args: object, **kwargs: object) -> main.found_art.FoundArtSummary:
        received.update(kwargs)
        return main.found_art.FoundArtSummary(
            generated_at=datetime(2026, 7, 23, tzinfo=UTC),
            week_start=datetime(2026, 7, 17, tzinfo=UTC).date(),
            playlist_id="found-art",
            requested_count=20,
            seed_count=1,
            history_tracks=100,
            history_scrobbles=1000,
            live_scrobbles_added=2,
            candidate_count=50,
            playlist_length_before=5,
            playlist_length_after=5,
            dry_run=True,
            seeds=(recommendation_seed,),
            results=(
                main.found_art.FoundArtResult(
                    candidate=candidate,
                    match=match,
                    action="would add",
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            found_art_playlist="spotify:playlist:foundart",
            lastfm_api_key="api-key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main.found_art, "run_found_art", run)

    result = CliRunner().invoke(main.app, ["found-art", "--dry-run"])

    assert result.exit_code == 0
    assert received["count"] == 20
    assert received["dry_run"] is True
    assert "New Artist" in result.output
    assert "would add" in result.output
    assert "2026-07-17 through 2026-07-23" in result.output
    assert "Spotify was unchanged" in result.output


def test_found_art_count_and_maximum_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(
        main.app,
        [
            "found-art",
            "--count",
            "10",
            "--max-playlist-length",
            "50",
        ],
    )

    assert result.exit_code != 0
    assert "either --count or --max-playlist-length" in result.output
