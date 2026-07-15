"""Tests for the live-first analyse-library CLI."""

import pytest

from spotify_manager import main


def test_analyse_library_command_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())

    def complete_sync(*_args, **kwargs):
        kwargs["progress_callback"]("albums", 2, 2, "Complete")
        return main.library_sync.LibrarySyncSummary(
            run_id="run-1",
            backup_dir="/tmp/backup/run-1",
            resources=(
                main.library_sync.ResourceSyncSummary(
                    resource="albums",
                    source="live_api",
                    previous=1,
                    current=2,
                    added=1,
                    removed=0,
                ),
                main.library_sync.ResourceSyncSummary(
                    resource="tracks",
                    source="export_fallback",
                    previous=2,
                    current=2,
                    added=0,
                    removed=0,
                ),
                main.library_sync.ResourceSyncSummary(
                    resource="artists",
                    source="verified_fallback",
                    previous=3,
                    current=2,
                    added=0,
                    removed=1,
                ),
            ),
        )

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_routine",
        complete_sync,
    )

    main.analyse_library()

    output = capsys.readouterr().out
    assert "Library mirror updated" in output
    assert "Run: run-1" in output
    assert "Audit manifest: /tmp/backup/run-1/manifest.json" in output


def test_analyse_library_command_handles_rate_limit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(main, "review_client", lambda: object())

    def rate_limited(*_args, **_kwargs):
        raise main.library_sync.SpotifyRateLimitError(120)

    monkeypatch.setattr(
        main.library_sync,
        "analyse_library_routine",
        rate_limited,
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.analyse_library()

    assert exc.value.exit_code == 0
    output = capsys.readouterr().out
    assert "Spotify rate limit reached" in output
    assert "rerun the same command to resume" in output


def test_restore_library_sync_command(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def restore(run_id: str):
        calls.append(run_id)
        return ("albums_total_new.json", "stats_history.json")

    monkeypatch.setattr(main.library_sync, "restore_library_sync", restore)

    main.restore_library_sync_command("run-1", yes=True)

    assert calls == ["run-1"]
    assert "albums_total_new.json" in capsys.readouterr().out
