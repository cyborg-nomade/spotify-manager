"""Tests for review-album-limits CLI prompting."""

from types import SimpleNamespace

import pytest
from rich.console import Console
from spotipy.exceptions import SpotifyException

from spotify_manager import main


class FakeProgress:
    """Small progress stand-in recording start/stop calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def stop(self) -> None:
        self.calls.append("stop")

    def start(self) -> None:
        self.calls.append("start")


def test_ask_review_action_pauses_progress_while_prompting(monkeypatch) -> None:
    progress = FakeProgress()
    prompt_call: dict[str, object] = {}

    def fake_ask(
        prompt: str,
        choices: list[str],
        default: str,
        console: Console,
    ) -> str:
        prompt_call.update(
            {
                "prompt": prompt,
                "choices": choices,
                "default": default,
                "console": console,
            }
        )
        return "r"

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)
    console = Console()

    result = main.ask_review_action(
        console,
        SimpleNamespace(decision="remove"),
        progress,
    )

    assert result == "r"
    assert progress.calls == ["stop", "start"]
    assert prompt_call["default"] == "r"
    assert prompt_call["console"] is console


def test_ask_review_action_defaults_to_skip_for_non_remove(monkeypatch) -> None:
    prompt_call: dict[str, object] = {}

    def fake_ask(
        prompt: str,
        choices: list[str],
        default: str,
        console: Console,
    ) -> str:
        prompt_call["default"] = default
        return "s"

    monkeypatch.setattr(main.Prompt, "ask", fake_ask)

    result = main.ask_review_action(Console(), SimpleNamespace(decision="keep"))

    assert result == "s"
    assert prompt_call["default"] == "s"


def test_review_client_disables_spotipy_retries(monkeypatch) -> None:
    calls: list[dict[str, int]] = []
    fake_client = object()
    monkeypatch.setattr(main, "_review_client", None)

    def fake_get_spotipy_client(**kwargs):
        calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(main, "get_spotipy_client", fake_get_spotipy_client)

    assert main.review_client() is fake_client
    assert main.review_client() is fake_client
    assert calls == [
        {
            "retries": 0,
            "status_retries": 0,
            "status_forcelist": main.DISABLED_SPOTIFY_STATUS_FORCELIST,
            "event_callback": main.typer.echo,
        }
    ]


def test_review_album_limits_command_handles_transient_server_error(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())

    def fail_review(*_args, **_kwargs):
        raise main.review_album_limits.SpotifyTransientServerError(
            503,
            "checking/following artist for OK Computer - Radiohead",
            3,
        )

    monkeypatch.setattr(main.review_album_limits, "review_album_limits", fail_review)

    with pytest.raises(main.typer.Exit) as exc:
        main.review_album_limits_command()

    assert exc.value.exit_code == 0
    output = capsys.readouterr().out
    assert "Spotify API temporarily unavailable (503) after 3 attempts" in output
    assert "Progress was saved up to the last successful removal." in output


def test_review_album_limits_command_validates_threshold_and_runs_callbacks(
    monkeypatch,
    capsys,
) -> None:
    with pytest.raises(main.typer.BadParameter):
        main.review_album_limits_command(threshold=1.1)

    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "s")
    received: dict[str, object] = {}

    def complete(*_args, **kwargs):
        received.update(kwargs)
        kwargs["progress_callback"](1, 1)
        assert kwargs["action_reader"](None, SimpleNamespace(decision="keep")) == "s"
        for line in (
            "Followed artist A",
            "Updated stats_history",
            "album keep: yes",
            "Kept anyway: Album",
            "remove candidate: Album",
            "Removed: Album",
            "Live liked tracks: 0",
            "Skipped: Album",
            "Review complete",
        ):
            kwargs["echo"](line)

    monkeypatch.setattr(main.review_album_limits, "review_album_limits", complete)

    main.review_album_limits_command(
        threshold=0.5,
        no_cache=True,
        refresh_cache=True,
    )

    assert received["use_cache"] is False
    assert received["refresh_cache"] is True
    assert "Review complete" in capsys.readouterr().out


def test_review_album_limits_command_handles_rate_limit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.review_album_limits,
        "review_album_limits",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            main.review_album_limits.SpotifyRateLimitError(60)
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.review_album_limits_command()

    assert exc.value.exit_code == 0
    assert "rate limit" in capsys.readouterr().out


def test_recover_removed_albums_command_runs_callbacks(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())
    received: dict[str, object] = {}

    def complete(*_args, **kwargs):
        received.update(kwargs)
        kwargs["progress_callback"](1, 1)
        for line in (
            "Followed credited artist A",
            "Would follow A",
            "Multiple credited artists",
            "Restored future release A",
            "Future release already saved",
            "Album unavailable",
            "Dry run complete",
        ):
            kwargs["echo"](line)

    monkeypatch.setattr(
        main.recover_removed_albums,
        "recover_removed_albums",
        complete,
    )

    main.recover_removed_albums_command(dry_run=True, limit=1)

    assert received["dry_run"] is True
    assert received["limit"] == 1
    assert "Dry run complete" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        main.recover_removed_albums.SpotifyRateLimitError(60),
        main.recover_removed_albums.SpotifyTransientServerError(502, "recovering", 3),
    ],
)
def test_recover_removed_albums_command_pauses_on_retryable_errors(
    monkeypatch,
    error,
) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.recover_removed_albums,
        "recover_removed_albums",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.recover_removed_albums_command(dry_run=False, limit=None)

    assert exc.value.exit_code == 0


def test_review_artists_command_uses_configured_queues_and_limit(
    monkeypatch,
    capsys,
) -> None:
    spotify = object()
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist="queue1",
            the_queue_2_playlist="spotify:playlist:queue2",
            the_queue_3_playlist="https://open.spotify.com/playlist/queue3",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: spotify)

    def complete_review(client, playlists, **kwargs):
        received.update(
            {
                "client": client,
                "playlists": playlists,
                "limit": kwargs["limit"],
                "refresh_cache": kwargs["refresh_cache"],
            }
        )
        kwargs["progress_callback"](1, 1, "Complete")
        for line in (
            "Auto-unfollowed Artist",
            "Planned automatic unfollow Artist",
            "Queued Artist",
            "Moved Artist",
            "Already queued Artist",
            "Declined Artist",
            "No eligible track",
            "No unliked track",
        ):
            kwargs["echo"](line)
        return main.artist_review.ArtistReviewSummary(
            total_pending_at_start=1,
            reviewed=1,
            unfollowed=0,
            queued=0,
            moved=1,
            already_queued=0,
            declined=0,
            no_action=0,
            skipped=0,
            paused=False,
        )

    monkeypatch.setattr(main.artist_review, "review_artists", complete_review)

    main.review_artists_command(refresh_cache=True, limit=1)

    assert received["client"] is spotify
    assert received["playlists"] == main.artist_review.QueuePlaylists(
        "queue1", "queue2", "queue3"
    )
    assert received["limit"] == 1
    assert received["refresh_cache"] is True
    output = capsys.readouterr().out
    assert "Artist review complete" in output
    assert "Moved" in output


def test_review_artists_command_handles_rate_limit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist="queue1",
            the_queue_2_playlist="queue2",
            the_queue_3_playlist="queue3",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())

    def rate_limited(*_args, **_kwargs):
        raise main.artist_review.SpotifyRateLimitError(120)

    monkeypatch.setattr(main.artist_review, "review_artists", rate_limited)

    with pytest.raises(main.typer.Exit) as exc:
        main.review_artists_command(refresh_cache=False, limit=None)

    assert exc.value.exit_code == 0
    output = capsys.readouterr().out
    assert "Spotify rate limit reached" in output
    assert "try again in 2 minutes (at " in output
    assert "pending automatic decisions were saved" in output


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (
            main.artist_review.SpotifyTransientServerError(502, "reviewing", 3),
            0,
        ),
        (main.artist_review.ArtistReviewError("review failed"), 1),
        (SpotifyException(500, -1, "server failed"), 1),
    ],
)
def test_review_artists_command_reports_remaining_operational_errors(
    monkeypatch,
    error,
    exit_code,
) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist="queue1",
            the_queue_2_playlist="queue2",
            the_queue_3_playlist="queue3",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.artist_review,
        "review_artists",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.review_artists_command(refresh_cache=False, limit=None)

    assert exc.value.exit_code == exit_code


def test_review_artists_command_reports_bad_queue_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist=None,
            the_queue_2_playlist=None,
            the_queue_3_playlist=None,
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.review_artists_command(refresh_cache=False, limit=None)

    assert exc.value.exit_code == 1
