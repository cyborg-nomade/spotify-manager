"""Tests for the New Wine CLI command."""

from types import SimpleNamespace

from rich.console import Console
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
