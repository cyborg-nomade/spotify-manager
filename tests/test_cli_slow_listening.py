"""Tests for the Slow Listening CLI command."""

from types import SimpleNamespace

from rich.console import Console
from typer.testing import CliRunner

from spotify_manager import main


def release(
    spotify_id: str,
    name: str,
) -> main.slow_listening.DiscographyRelease:
    """Build one equal-date prompt candidate."""
    return main.slow_listening.DiscographyRelease(
        spotify_id=spotify_id,
        uri=f"spotify:album:{spotify_id}",
        name=name,
        release_type="Album",
        release_date="2020-01-01",
        chronology_date="2020-01-01",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        identity=name.casefold(),
        saved=False,
        plain=True,
        edition_rank=0,
    )


def playlist_track() -> main.new_wine.PlaylistTrack:
    """Build one Slow Listening prompt source."""
    source_release = main.new_wine.ReleaseCandidate(
        spotify_id="album",
        uri="spotify:album:album",
        name="Album",
        release_type="Album",
        release_date="2020-01-01",
        total_tracks=2,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )
    return main.new_wine.PlaylistTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Current",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        release=source_release,
    )


def test_release_order_prompt_accepts_a_complete_permutation(monkeypatch) -> None:
    """Equal-date releases should be returned in the requested order."""
    first = release("first", "First")
    second = release("second", "Second")
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "2,1")

    order = main.ask_slow_listening_release_order(
        Console(),
        "2020-01-01",
        (first, second),
    )

    assert order == ("second", "first")


def test_track_action_prompt_can_skip_proposed_candidate(monkeypatch) -> None:
    """The prompt should show and allow skipping the proposed next track."""
    prompts: list[str] = []

    def answer(prompt: str, *_args, **_kwargs) -> str:
        prompts.append(prompt)
        return "s"

    monkeypatch.setattr(main.Prompt, "ask", answer)

    choice = main.ask_slow_listening_action(
        Console(),
        playlist_track(),
        main.new_wine.ReleaseTrack(
            spotify_id="next",
            uri="spotify:track:next",
            name="Next",
            disc_number=1,
            track_number=2,
        ),
        release("album", "Album"),
    )

    assert choice == main.slow_listening.CHOICE_SKIP
    assert "Next (Album)" in prompts[0]


def test_flush_slow_listening_dry_run_uses_configured_playlist(
    monkeypatch,
) -> None:
    """The CLI should pass the parsed playlist and dry-run mode."""
    received: dict[str, object] = {}

    def flush(_spotify, playlist_id, **kwargs):
        received.update(
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            order_reader=callable(kwargs["order_reader"]),
            completion_notifier=callable(kwargs["completion_notifier"]),
            action_reader=callable(kwargs["action_reader"]),
        )
        return main.slow_listening.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=1,
            completed_artists=0,
            skipped=0,
            paused=False,
            dry_run=True,
            resumed=False,
            results=(
                main.slow_listening.FlushResult(
                    source_track="Current",
                    source_release="First Album",
                    artist="Artist",
                    action="advance",
                    target_track="Next",
                    target_release="First Album",
                    dry_run=True,
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            slow_listening_playlist="https://open.spotify.com/playlist/slow",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.slow_listening,
        "flush_slow_listening",
        flush,
    )

    result = CliRunner().invoke(
        main.app,
        ["flush-slow-listening", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received == {
        "playlist_id": "slow",
        "dry_run": True,
        "order_reader": True,
        "completion_notifier": True,
        "action_reader": True,
    }
    assert "Dry run: 1/1 processed" in result.output
    assert "Current" in result.output
    assert "Next" in result.output
