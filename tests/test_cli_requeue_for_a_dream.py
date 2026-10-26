"""Tests for the Requeue for a Dream CLI command."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_flush_requeue_dry_run_uses_the_configured_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI should honor the existing env spelling and dry-run mode."""
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                reqeueue_for_a_dream_playlist="https://open.spotify.com/playlist/requeue"
            )
        ),
    )
    monkeypatch.setattr(main, "review_client", Mock(return_value=object()))
    scenario = FlushRequeueDryRunUsesTheConfiguredPlaylistScenario(received=received)
    monkeypatch.setattr(
        main.requeue_for_a_dream, "flush_requeue_for_a_dream", scenario.flush
    )
    result = CliRunner().invoke(main.app, ["flush-requeue-for-a-dream", "--dry-run"])
    assert result.exit_code == 0
    assert received == {"playlist_id": "requeue", "dry_run": True, "retry_call": True}
    assert "Requeue for a Dream" in result.output
    assert "Second" in result.output
    assert "Opening Track" in result.output
    assert "preview only" in result.output


@dataclass
class FlushRequeueDryRunUsesTheConfiguredPlaylistScenario:
    """Retain the original flush requeue dry run uses the configured playlist fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def flush(
        self, _spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> main.requeue_for_a_dream.RequeueForADreamSummary:
        """Execute the original flush mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            retry_call=callable(getattr(kwargs["retry_call"], "attempts", None)),
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
