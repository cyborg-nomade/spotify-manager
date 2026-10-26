"""Tests for the split library-analysis CLI commands."""

from dataclasses import dataclass
from io import StringIO
from typing import Any
from unittest.mock import Mock

import pytest
from rich.console import Console

from spotify_manager import main


def summary(
    mode: main.library_sync.AnalysisMode,
) -> main.library_sync.LibrarySyncSummary:
    """Return one small completed analysis summary."""
    source = "YourLibrary.json" if mode == "async" else "live_api"
    resources: tuple[main.library_sync.ResourceName, ...] = (
        "albums",
        "tracks",
        "artists",
    )
    return main.library_sync.LibrarySyncSummary(
        run_id="run-1",
        mode=mode,
        backup_dir="/tmp/backup/run-1",
        resources=tuple(
            main.library_sync.ResourceSyncSummary(
                resource=resource,
                source=source,
                previous=1,
                current=2,
                added=1,
                removed=0,
            )
            for resource in resources
        ),
    )


def test_async_command_prints_summary_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Async command prints summary without constructing client.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    scenario = AsyncCommandPrintsSummaryWithoutConstructingClientScenario()
    monkeypatch.setattr(main, "review_client", scenario.no_client)
    monkeypatch.setattr(
        main.library_sync, "analyse_library_async_routine", scenario.complete_export
    )
    main.analyse_library_async()
    output = capsys.readouterr().out
    assert "Export library mirror updated" in output
    assert "Run: run-1" in output
    assert "Audit manifest: /tmp/backup/run-1/manifest.json" in output


def test_sync_command_uses_no_retry_client_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sync command uses no retry client and prints summary.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    spotify = object()
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    calls: list[object] = []
    scenario = SyncCommandUsesNoRetryClientAndPrintsSummaryScenario(calls=calls)
    monkeypatch.setattr(
        main.library_sync, "analyse_library_sync_routine", scenario.complete_sync
    )
    main.analyse_library_sync()
    assert calls == [spotify]
    assert "Live library mirror updated" in capsys.readouterr().out


def test_sync_command_handles_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())

    def rate_limited(*_args: Any, **_kwargs: Any) -> None:
        raise main.library_sync.SpotifyRateLimitError(120)

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_sync_routine",
        rate_limited,
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.analyse_library_sync()

    assert exc.value.exit_code == 0
    output = capsys.readouterr().out
    assert "Spotify rate limit reached" in output
    assert "rerun the same command to resume" in output


def test_sync_command_handles_clean_retry_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())

    def cancelled(*_args: Any, **_kwargs: Any) -> None:
        raise main.library_sync.LibraryAnalysisCancelledError("Analysis paused.")

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_sync_routine",
        cancelled,
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.analyse_library_sync()

    assert exc.value.exit_code == 0
    assert "Progress was saved" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "exit_code", "message"),
    [
        (KeyboardInterrupt(), 0, "Analysis paused"),
        (
            main.library_sync.LibrarySyncError("invalid mirror"),
            1,
            "No partial staging data was published",
        ),
    ],
)
def test_analysis_command_handles_interrupt_and_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    exit_code: int,
    message: str,
) -> None:
    def fail(**_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_async_routine",
        fail,
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.analyse_library_async()

    assert exc.value.exit_code == exit_code
    assert message in capsys.readouterr().out


def test_retry_wait_can_rotate_credentials_and_retry_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTTY:
        def isatty(self) -> bool:
            return True

        def fileno(self) -> int:
            return 0

        def read(self, _size: int) -> str:
            return "r"

    class FakeSpotify:
        def __init__(self) -> None:
            self.rotations = 0

        def rotate_credentials(self) -> str:
            self.rotations += 1
            return "app5"

    stdin = FakeTTY()
    spotify = FakeSpotify()
    output = StringIO()
    monkeypatch.setattr(main.sys, "stdin", stdin)
    monkeypatch.setattr(main.termios, "tcgetattr", lambda _descriptor: object())
    monkeypatch.setattr(main.termios, "tcsetattr", lambda *_args: None)
    monkeypatch.setattr(main.tty, "setcbreak", lambda _descriptor: None)
    monkeypatch.setattr(main.select, "select", lambda *_args: ([stdin], [], []))

    should_retry = main.wait_for_library_retry(
        Console(file=output, force_terminal=False),
        main.library_sync.RetryNotice(500, "reading followed artists", 1, 60),
        spotify,  # type: ignore[arg-type]
    )

    assert should_retry is True
    assert spotify.rotations == 1
    assert "Rotated to app5; retrying now." in output.getvalue()


def test_retry_wait_sleeps_without_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry wait sleeps without interactive terminal.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
    """

    delays: list[float] = []
    monkeypatch.setattr(main.sys, "stdin", NonInteractiveInput())
    monkeypatch.setattr(main.time, "sleep", delays.append)

    should_retry = main.wait_for_library_retry(
        Console(file=StringIO(), force_terminal=False),
        main.library_sync.RetryNotice(None, "connecting", 1, 3),
        object(),  # type: ignore[arg-type]
    )

    assert should_retry is True
    assert delays == [3]


@pytest.mark.parametrize("rotation_mode", ["quit", "unsupported", "failure"])
def test_retry_wait_can_quit_after_rotation_problem(
    monkeypatch: pytest.MonkeyPatch,
    rotation_mode: str,
) -> None:
    responses = iter(["q"] if rotation_mode == "quit" else ["r", "q"])

    class FakeTTY:
        @staticmethod
        def isatty() -> bool:
            return True

        @staticmethod
        def fileno() -> int:
            return 0

        @staticmethod
        def read(_size: int) -> str:
            return next(responses)

    class FailingRotation:
        @staticmethod
        def rotate_credentials() -> str:
            raise RuntimeError("rotation failed")

    stdin = FakeTTY()
    spotify = FailingRotation() if rotation_mode == "failure" else object()
    output = StringIO()
    monkeypatch.setattr(main.sys, "stdin", stdin)
    monkeypatch.setattr(main.termios, "tcgetattr", lambda _descriptor: object())
    monkeypatch.setattr(main.termios, "tcsetattr", lambda *_args: None)
    monkeypatch.setattr(main.tty, "setcbreak", lambda _descriptor: None)
    monkeypatch.setattr(main.select, "select", lambda *_args: ([stdin], [], []))

    should_retry = main.wait_for_library_retry(
        Console(file=output, force_terminal=False),
        main.library_sync.RetryNotice(502, "loading albums", 1, 60),
        spotify,  # type: ignore[arg-type]
    )

    assert should_retry is False
    if rotation_mode == "unsupported":
        assert "cannot rotate credentials" in output.getvalue()
    if rotation_mode == "failure":
        assert "Could not rotate credentials" in output.getvalue()


def test_restore_library_sync_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def restore(run_id: str) -> tuple[str, ...]:
        calls.append(run_id)
        return ("albums_total_new_sync.json", "stats_history_sync.json")

    monkeypatch.setattr(main.library_sync, "restore_library_sync", restore)

    main.restore_library_sync_command("run-1", yes=True)

    assert calls == ["run-1"]
    assert "albums_total_new_sync.json" in capsys.readouterr().out


@dataclass
class AsyncCommandPrintsSummaryWithoutConstructingClientScenario:
    """Retain the original async command prints summary without constructing client
    fixture.
    """

    def no_client(self) -> None:
        """Execute the original no client mock boundary."""
        raise AssertionError("export analysis must not construct a Spotify client")

    def complete_export(self, **kwargs: Any) -> main.library_sync.LibrarySyncSummary:
        """Execute the original complete export mock boundary.

        Args:
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        for resource in ("albums", "tracks", "artists"):
            kwargs["progress_callback"].progress(resource, 2, 2, "Complete")
        return summary("async")


@dataclass
class SyncCommandUsesNoRetryClientAndPrintsSummaryScenario:
    """Retain the original sync command uses no retry client and prints summary fixture.

    Args:
        calls: Original calls observation or resource.
    """

    calls: list[object]

    def complete_sync(
        self, client: object, **kwargs: Any
    ) -> main.library_sync.LibrarySyncSummary:
        """Execute the original complete sync mock boundary.

        Args:
            client: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append(client)
        kwargs["progress_callback"].progress("albums", 1, 1, "Complete")
        return summary("sync")


class NonInteractiveInput:
    """Provide a noninteractive standard-input boundary."""

    @staticmethod
    def isatty() -> bool:
        """Report whether retry input can be read interactively.

        Returns:
            False for the noninteractive retry fixture.
        """
        return False
