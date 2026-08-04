"""Tests for the Requeue for a Dream CLI command."""

from datetime import UTC
from datetime import datetime
from types import SimpleNamespace

from typer.testing import CliRunner

from spotify_manager import main


def test_flush_requeue_dry_run_uses_the_configured_playlist(monkeypatch) -> None:
    """The CLI should honor the existing env spelling and dry-run mode."""
    received: dict[str, object] = {}

    def flush(_spotify, playlist_id, **kwargs):
        received.update(
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            retry_call=callable(kwargs["retry_call"]),
        )
        return main.requeue_for_a_dream.RequeueForADreamSummary(
            recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            action="advance",
            playlist_length_before=1,
            playlist_length_after=1,
            artist="Artist",
            source_track="Current",
            source_release="First",
            target_track="Opening Track",
            target_release="Second",
            target_release_type="Album",
            target_release_date="2022-01-01",
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            reqeueue_for_a_dream_playlist=("https://open.spotify.com/playlist/requeue"),
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(
        main.requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        flush,
    )

    result = CliRunner().invoke(
        main.app,
        ["flush-requeue-for-a-dream", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received == {
        "playlist_id": "requeue",
        "dry_run": True,
        "retry_call": True,
    }
    assert "Requeue for a Dream" in result.output
    assert "Second" in result.output
    assert "Opening Track" in result.output
    assert "preview only" in result.output
