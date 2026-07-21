"""Tests for the split library-analysis CLI commands."""

from typing import Any

import pytest

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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def no_client() -> None:
        raise AssertionError("export analysis must not construct a Spotify client")

    monkeypatch.setattr(main, "review_client", no_client)

    def complete_export(**kwargs: Any) -> main.library_sync.LibrarySyncSummary:
        for resource in ("albums", "tracks", "artists"):
            kwargs["progress_callback"](resource, 2, 2, "Complete")
        return summary("async")

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_async_routine",
        complete_export,
    )

    main.analyse_library_async()

    output = capsys.readouterr().out
    assert "Export library mirror updated" in output
    assert "Run: run-1" in output
    assert "Audit manifest: /tmp/backup/run-1/manifest.json" in output


def test_sync_command_uses_no_retry_client_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spotify = object()
    monkeypatch.setattr(main, "review_client", lambda: spotify)
    calls: list[object] = []

    def complete_sync(
        client: object,
        **kwargs: Any,
    ) -> main.library_sync.LibrarySyncSummary:
        calls.append(client)
        kwargs["progress_callback"]("albums", 1, 1, "Complete")
        return summary("sync")

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_sync_routine",
        complete_sync,
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
