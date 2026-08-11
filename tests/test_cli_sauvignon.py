"""Tests for the Sauvignon recommendation CLI command."""

from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

from typer.testing import CliRunner

from spotify_manager import main


def test_sauvignon_dry_run_defaults_to_playlist_cap_and_prints_result(
    monkeypatch,
) -> None:
    received: dict[str, object] = {}
    option = main.sauvignon.SpotifyAlbumOption(
        spotify_id="album-id",
        uri="spotify:album:album-id",
        artist_id="artist-id",
        artist="New Artist",
        album="New Album",
        release_type="Album",
        release_date="2024-01-01",
        total_tracks=10,
        source_track="Evidence",
        source_track_id="evidence-id",
        search_rank=1,
        track_similarity=1.0,
        track_popularity=50,
    )
    recommendation = main.sauvignon.AlbumRecommendation(
        artist="New Artist",
        album="New Album",
        key=("new artist", "new album"),
        score=2.0,
        best_match=0.95,
        supporting_tracks=("New Artist - Evidence",),
        options=(option,),
        base_rank=1,
        weekly_rank=0.8,
    )

    def run(*_args: object, **kwargs: object) -> main.sauvignon.SauvignonSummary:
        received.update(kwargs)
        return main.sauvignon.SauvignonSummary(
            generated_at=datetime(2026, 8, 11, tzinfo=UTC),
            week_start=datetime(2026, 8, 7, tzinfo=UTC).date(),
            playlist_id="sauvignon",
            requested_count=2,
            history_albums=100,
            history_scrobbles=1000,
            live_scrobbles_added=3,
            seed_count=30,
            track_candidate_count=100,
            album_candidate_count=25,
            playlist_length_before=18,
            playlist_length_after=18,
            paused=False,
            dry_run=True,
            results=(
                main.sauvignon.SauvignonResult(
                    recommendation,
                    option,
                    main.sauvignon.FirstTrack(
                        "first",
                        "spotify:track:first",
                        "Opening",
                    ),
                    "would add",
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            sauvignon_terre_neuve_playlist="spotify:playlist:sauvignon",
            lastfm_api_key="api-key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.sauvignon, "fill_sauvignon_from_lastfm", run)

    result = CliRunner().invoke(
        main.app,
        ["fill-sauvignon-from-lastfm", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received["count"] is None
    assert received["max_playlist_length"] == 20
    assert received["dry_run"] is True
    assert "New Artist" in result.output
    assert "Opening" in result.output
    assert "would add" in result.output
    assert "2026-08-07 through 2026-08-13" in result.output
    assert "Sauvignon 18 -> 18" in result.output


def test_sauvignon_count_and_maximum_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(
        main.app,
        [
            "fill-sauvignon-from-lastfm",
            "--count",
            "5",
            "--max-playlist-length",
            "20",
        ],
    )

    assert result.exit_code != 0
    assert "either --count or --max-playlist-length" in result.output
