"""Tests for the New Wine CLI command."""

from types import SimpleNamespace

import pytest
from rich.console import Console
from spotipy.exceptions import SpotifyException
from typer.testing import CliRunner

from spotify_manager import main


def test_new_wine_release_prompt_accepts_drop(monkeypatch) -> None:
    """The single-release prompt should expose an explicit drop action."""
    release = main.new_wine.ReleaseCandidate(
        spotify_id="release",
        uri="spotify:album:release",
        name="Release",
        release_type="Single",
        release_date="2026-01-01",
        total_tracks=1,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )
    source = main.new_wine.PlaylistTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Track",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        release=release,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "d")

    choice = main.ask_new_wine_release_choice(
        Console(),
        source,
        (release,),
    )

    assert choice == main.new_wine.CHOICE_DROP


def test_new_wine_album_endpoint_prompt_accepts_finish(monkeypatch) -> None:
    """Album endpoints should finish without describing it as a drop."""
    release = main.new_wine.ReleaseCandidate(
        spotify_id="release",
        uri="spotify:album:release",
        name="Release",
        release_type="Album",
        release_date="2026-01-01",
        total_tracks=8,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )
    source = main.new_wine.PlaylistTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Final Track",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        release=release,
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        main.Prompt,
        "ask",
        lambda prompt, **_kwargs: prompts.append(prompt) or "f",
    )

    choice = main.ask_new_wine_release_choice(
        Console(),
        source,
        (release,),
    )

    assert choice == main.new_wine.CHOICE_FINISH
    assert "[f]inish" in prompts[0]


def test_flush_new_wine_dry_run_uses_configured_playlists(monkeypatch) -> None:
    """The CLI should pass both parsed playlists and dry-run mode."""
    received: dict[str, object] = {}

    def flush(_spotify, new_playlist, sauvignon_playlist, **kwargs):
        received.update(
            new_playlist=new_playlist,
            sauvignon_playlist=sauvignon_playlist,
            wine_cellar_playlist=kwargs["wine_cellar_playlist_id"],
            no_discovery=kwargs["no_discovery"],
            dry_run=kwargs["dry_run"],
        )
        return main.new_wine.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=1,
            dropped=0,
            sent_to_sauvignon=0,
            completed_singles=0,
            skipped=0,
            albums_unsaved=0,
            paused=False,
            dry_run=True,
            resumed=False,
            results=(
                main.new_wine.FlushResult(
                    source_track="Current",
                    artist="Artist",
                    release="Release",
                    release_type="Album",
                    current_liked=True,
                    consecutive_unliked=0,
                    action="advance",
                    target_track="Next",
                    dry_run=True,
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            new_wine_from_old_bottles_playlist="spotify:playlist:new",
            sauvignon_terre_neuve_playlist="https://open.spotify.com/playlist/sauv",
            wine_cellar_playlist="spotify:playlist:cellar",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.new_wine, "flush_new_wine", flush)

    result = CliRunner().invoke(
        main.app,
        ["flush-new-wine", "--dry-run", "--no-discovery"],
    )

    assert result.exit_code == 0
    assert received == {
        "new_playlist": "new",
        "sauvignon_playlist": "sauv",
        "wine_cellar_playlist": "cellar",
        "no_discovery": True,
        "dry_run": True,
    }
    assert "Dry run: 1/1 processed" in result.output
    assert "Current" in result.output
    assert "Next" in result.output


def test_flush_new_wine_renders_detailed_results_and_refill(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            new_wine_from_old_bottles_playlist="new",
            sauvignon_terre_neuve_playlist="sauvignon",
            wine_cellar_playlist="cellar",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())

    def flush(*_args, **kwargs):
        for message in (
            "Added track",
            "Moved track",
            "Removed track",
            "Would add track",
            "No eligible track",
            "Source already removed",
            "Skipping duplicate",
        ):
            kwargs["echo"](message)
        kwargs["progress_callback"](1, 1, "Complete")
        return main.new_wine.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=0,
            dropped=1,
            sent_to_sauvignon=0,
            completed_singles=0,
            skipped=0,
            albums_unsaved=1,
            paused=True,
            dry_run=False,
            resumed=True,
            results=(
                main.new_wine.FlushResult(
                    source_track="Current",
                    artist="Artist",
                    release="Album",
                    release_type="Album",
                    current_liked=False,
                    consecutive_unliked=3,
                    action="drop",
                    album_unsaved=True,
                    advance_reason="next_liked_track",
                    drop_reason="manual_selection",
                    continuation_release="Next Album",
                    continuation_track="Next Track",
                ),
            ),
            refill=main.new_wine.CellarRefillSummary(
                target_size=10,
                before=8,
                after=9,
                added=1,
                removed_from_cellar=1,
                ineligible=1,
                no_discovery=True,
                results=(
                    main.new_wine.CellarRefillResult(
                        source_track="Cellar Track",
                        artist="Cellar Artist",
                        action="moved",
                        liked_tracks=18,
                        saved_albums=3,
                    ),
                    main.new_wine.CellarRefillResult(
                        source_track="Hidden",
                        artist="Hidden Artist",
                        action="ineligible",
                    ),
                ),
            ),
        )

    monkeypatch.setattr(main.new_wine, "flush_new_wine", flush)

    main.flush_new_wine_command(dry_run=False, no_discovery=True)

    output = capsys.readouterr().out
    assert "chosen" in output
    assert "Wine Cellar (no-discovery)" in output
    assert "Resumed the previously saved flush" in output
    assert "Flush paused" in output


@pytest.mark.parametrize(
    ("error", "exit_code", "message"),
    [
        (
            main.review_album_limits.SpotifyRateLimitError(120),
            0,
            "rate limit reached",
        ),
        (
            main.review_album_limits.SpotifyTransientServerError(
                502,
                "loading playlist",
                3,
            ),
            0,
            "temporarily unavailable",
        ),
        (main.new_wine.NewWineError("state failed"), 1, "state failed"),
        (SpotifyException(500, -1, "server failed"), 1, "HTTP 500"),
        (KeyboardInterrupt(), 0, "flush paused"),
    ],
)
def test_flush_new_wine_reports_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    exit_code: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            new_wine_from_old_bottles_playlist="new",
            sauvignon_terre_neuve_playlist="sauvignon",
            wine_cellar_playlist="cellar",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(main.new_wine, "flush_new_wine", fail)

    with pytest.raises(main.typer.Exit) as exc:
        main.flush_new_wine_command(dry_run=False, no_discovery=False)

    assert exc.value.exit_code == exit_code
    assert message.casefold() in capsys.readouterr().out.casefold()


def test_flush_new_wine_reports_missing_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            new_wine_from_old_bottles_playlist=None,
            sauvignon_terre_neuve_playlist=None,
            wine_cellar_playlist=None,
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.flush_new_wine_command(dry_run=False, no_discovery=False)

    assert exc.value.exit_code == 1
    assert "not configured" in capsys.readouterr().out
