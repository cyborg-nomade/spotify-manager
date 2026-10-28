"""Tests for review-album-limits CLI prompting."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from rich.console import Console
from spotipy.exceptions import SpotifyException

from spotify_manager import main
from spotify_manager.interfaces.cli.output import TYPER_OUTPUT


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


def test_review_client_disables_spotipy_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review client disables spotipy retries.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """
    calls: list[dict[str, int]] = []
    fake_client = object()
    monkeypatch.setattr(main, "_review_client", None)
    scenario = ReviewClientDisablesSpotipyRetriesScenario(
        calls=calls, fake_client=fake_client
    )
    monkeypatch.setattr(main, "get_spotipy_client", scenario.fake_get_spotipy_client)
    assert (main.review_client()) is fake_client
    assert (main.review_client()) is fake_client
    assert calls == [
        {
            "retries": 0,
            "status_retries": 0,
            "status_forcelist": main.DISABLED_SPOTIFY_STATUS_FORCELIST,
            "event_callback": TYPER_OUTPUT,
        }
    ]


def test_review_album_limits_command_handles_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify review album limits command handles transient server error.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Captured console output.
    """
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )

    error = main.review_album_limits.SpotifyTransientServerError(
        503, "checking/following artist for OK Computer - Radiohead", 3
    )
    monkeypatch.setattr(
        main.review_album_limits,
        "review_album_limits",
        AsyncMock(side_effect=Mock(side_effect=error)),
    )

    with pytest.raises(main.typer.Exit) as exc:
        (main.review_album_limits_command())

    assert exc.value.exit_code == 0
    output = capsys.readouterr().out
    assert "Spotify API temporarily unavailable (503) after 3 attempts" in output
    assert "Progress was saved up to the last successful removal." in output


def test_review_album_limits_command_validates_threshold_and_runs_callbacks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review album limits command validates threshold and runs callbacks.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    with pytest.raises(main.typer.BadParameter):
        (main.review_album_limits_command(threshold=1.1))
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    monkeypatch.setattr(main.Prompt, "ask", Mock(return_value="s"))
    received: dict[str, object] = {}
    scenario = ReviewAlbumLimitsCommandValidatesThresholdAndRunsCallbacksScenario(
        received=received
    )
    monkeypatch.setattr(
        main.review_album_limits,
        "review_album_limits",
        AsyncMock(side_effect=scenario.complete),
    )
    (main.review_album_limits_command(threshold=0.5, no_cache=True, refresh_cache=True))
    assert received["use_cache"] is False
    assert received["refresh_cache"] is True
    assert "Review complete" in capsys.readouterr().out


def test_review_album_limits_command_handles_rate_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify review album limits command handles rate limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Captured console output.
    """
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    monkeypatch.setattr(
        main.review_album_limits,
        "review_album_limits",
        AsyncMock(
            side_effect=Mock(
                side_effect=main.review_album_limits.SpotifyRateLimitError(60)
            )
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        (main.review_album_limits_command())

    assert exc.value.exit_code == 0
    assert "rate limit" in capsys.readouterr().out


def test_recover_removed_albums_command_runs_callbacks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recover removed albums command runs callbacks.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    received: dict[str, object] = {}
    scenario = RecoverRemovedAlbumsCommandRunsCallbacksScenario(received=received)
    monkeypatch.setattr(
        main.recover_removed_albums,
        "recover_removed_albums",
        AsyncMock(side_effect=scenario.complete),
    )
    (main.recover_removed_albums_command(dry_run=True, limit=1))
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
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Verify recover removed albums command pauses on retryable errors.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        error: Operational failure raised by the routine.
    """
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    monkeypatch.setattr(
        main.recover_removed_albums,
        "recover_removed_albums",
        AsyncMock(side_effect=Mock(side_effect=error)),
    )

    with pytest.raises(main.typer.Exit) as exc:
        (main.recover_removed_albums_command(dry_run=False, limit=None))

    assert exc.value.exit_code == 0


def test_review_artists_command_uses_configured_queues_and_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review artists command uses configured queues and limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    spotify = object()
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                the_queue_playlist="queue1",
                the_queue_2_playlist="spotify:playlist:queue2",
                the_queue_3_playlist="https://open.spotify.com/playlist/queue3",
            )
        ),
    )
    monkeypatch.setattr(
        main, "_native_review_client", AsyncMock(side_effect=Mock(return_value=spotify))
    )
    scenario = ReviewArtistsCommandUsesConfiguredQueuesAndLimitScenario(
        received=received
    )
    monkeypatch.setattr(
        main.artist_review,
        "review_artists",
        AsyncMock(side_effect=scenario.complete_review),
    )
    (main.review_artists_command(refresh_cache=True, limit=1))
    assert received["client"] is spotify
    assert received["playlists"] == main.artist_review.QueuePlaylists(
        "queue1", "queue2", "queue3"
    )
    assert received["limit"] == 1
    assert received["refresh_cache"] is True
    output = capsys.readouterr().out
    assert "Artist review complete" in output
    assert "Moved" in output


def test_review_artists_command_handles_rate_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify review artists command handles rate limit.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Captured console output.
    """
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                the_queue_playlist="queue1",
                the_queue_2_playlist="queue2",
                the_queue_3_playlist="queue3",
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )

    error = main.artist_review.SpotifyRateLimitError(120)
    monkeypatch.setattr(
        main.artist_review,
        "review_artists",
        AsyncMock(side_effect=Mock(side_effect=error)),
    )

    with pytest.raises(main.typer.Exit) as exc:
        (main.review_artists_command(refresh_cache=False, limit=None))

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
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    exit_code: int,
) -> None:
    """Verify review artists command reports remaining operational errors.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        error: Operational failure raised by the routine.
        exit_code: Expected command exit status.
    """
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                the_queue_playlist="queue1",
                the_queue_2_playlist="queue2",
                the_queue_3_playlist="queue3",
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    monkeypatch.setattr(
        main.artist_review,
        "review_artists",
        AsyncMock(side_effect=Mock(side_effect=error)),
    )

    with pytest.raises(main.typer.Exit) as exc:
        (main.review_artists_command(refresh_cache=False, limit=None))

    assert exc.value.exit_code == exit_code


def test_review_artists_command_reports_bad_queue_configuration(
    monkeypatch,
) -> None:
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
        (main.review_artists_command(refresh_cache=False, limit=None))

    assert exc.value.exit_code == 1


@dataclass
class ReviewClientDisablesSpotipyRetriesScenario:
    """Retain the original review client disables spotipy retries fixture.

    Args:
        calls: Original calls observation or resource.
        fake_client: Original fake client observation or resource.
    """

    calls: list[dict[str, int]]
    fake_client: object

    def fake_get_spotipy_client(self, **kwargs: Any) -> object:
        """Execute the original fake get spotipy client mock boundary.

        Args:
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append(kwargs)
        return self.fake_client


@dataclass
class ReviewAlbumLimitsCommandValidatesThresholdAndRunsCallbacksScenario:
    """Retain the original review album limits command validates threshold and runs
    callbacks fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    async def complete(self, *_args: Any, **kwargs: Any) -> None:
        """Execute the original complete mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.
        """
        self.received.update(kwargs)
        kwargs["progress_callback"].progress(1, 1)
        assert (
            await kwargs["action_reader"].choose_action(
                None, SimpleNamespace(decision="keep")
            )
            == "s"
        )
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
            kwargs["echo"].echo(line)


@dataclass
class RecoverRemovedAlbumsCommandRunsCallbacksScenario:
    """Retain the original recover removed albums command runs callbacks fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def complete(self, *_args: Any, **kwargs: Any) -> None:
        """Execute the original complete mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.
        """
        self.received.update(kwargs)
        kwargs["progress_callback"].progress(1, 1)
        for line in (
            "Followed credited artist A",
            "Would follow A",
            "Multiple credited artists",
            "Restored future release A",
            "Future release already saved",
            "Album unavailable",
            "Dry run complete",
        ):
            kwargs["echo"].echo(line)


@dataclass
class ReviewArtistsCommandUsesConfiguredQueuesAndLimitScenario:
    """Retain the original review artists command uses configured queues and limit
    fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def complete_review(
        self, client: Any, playlists: Any, **kwargs: Any
    ) -> main.artist_review.ArtistReviewSummary:
        """Execute the original complete review mock boundary.

        Args:
            client: Original external mock argument.
            playlists: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            {
                "client": client,
                "playlists": playlists,
                "limit": kwargs["limit"],
                "refresh_cache": kwargs["refresh_cache"],
            }
        )
        kwargs["progress_callback"].progress(1, 1, "Complete")
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
            kwargs["echo"].echo(line)
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
