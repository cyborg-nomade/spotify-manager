from datetime import date
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_check_new_releases_prompts_for_mapping_and_prints_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artist = main.release_check.RankedArtist("artist", "Artist", 100, 10)
    candidates = (
        main.release_check.SpotifyArtistCandidate(
            "first",
            "Artist One",
            "spotify:artist:first",
            40,
            100,
            1,
            False,
        ),
        main.release_check.SpotifyArtistCandidate(
            "second",
            "Artist Two",
            "spotify:artist:second",
            50,
            200,
            2,
            False,
        ),
    )
    result = main.release_check.ReleaseCheckResult(
        artist="Artist",
        artist_rank=10,
        artist_scrobbles=100,
        spotify_artist_id="second",
        release_id="release",
        release="New Album",
        release_type="Album",
        release_date="2026-08-05",
        first_track_id="track",
        first_track="Opening Track",
        linked_future_release=None,
        wine_cellar_action="would add",
        new_vintage_action="not applicable",
        reason=None,
        dry_run=True,
    )
    release = main.release_check.ReleaseCandidate(
        spotify_id="release",
        uri="spotify:album:release",
        name="New Album - Live at Rome (Deluxe)",
        release_type="Album",
        release_date="2026-08-05",
        release_date_precision="day",
        total_tracks=10,
        primary_artist_id="second",
        primary_artist_name="Artist",
    )
    track = main.release_check.ReleaseTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Opening Track",
        primary_artist_id="second",
        primary_artist_name="Artist",
        disc_number=1,
        track_number=1,
    )
    received: dict[str, object] = {}

    def run(*_args: object, **kwargs: object):
        received["dry_run"] = kwargs["dry_run"]
        received["search_choice"] = kwargs["artist_choice_reader"](
            artist,
            candidates,
        )
        received["artist_choice"] = kwargs["artist_choice_reader"](
            artist,
            (candidates[1],),
        )
        received["release_choice"] = kwargs["release_choice_reader"](
            artist,
            release,
            track,
            ("Wine Cellar", "New Vintage"),
            False,
        )
        return main.release_check.ReleaseCheckSummary(
            run_id="run",
            checked_from=date(2026, 1, 1),
            checked_through=date(2026, 8, 6),
            artists_total=1,
            artists_processed=1,
            dry_run=True,
            resumed=False,
            paused=False,
            history_refresh=None,
            results=(result,),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            wine_cellar_playlist="spotify:playlist:wine",
            new_vintage_playlist="spotify:playlist:vintage",
            lastfm_api_key="key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main.release_check, "run_release_check", run)

    cli_result = CliRunner().invoke(
        main.app,
        ["check-new-releases", "--dry-run"],
        input="n\nArtist Two\n1\na\n",
    )

    assert cli_result.exit_code == 0
    assert received == {
        "dry_run": True,
        "search_choice": "search:Artist Two",
        "artist_choice": "second",
        "release_choice": "add",
    }
    assert "Map Last.fm artist #10" in cli_result.output
    assert "New Spotify artist search" in cli_result.output
    assert "LIVE" in cli_result.output
    assert "DELUXE" in cli_result.output
    assert "New Album" in cli_result.output
    assert "would add" in cli_result.output
    assert "Last.fm history" in cli_result.output
    assert "permanent artist skips were persisted" in cli_result.output
