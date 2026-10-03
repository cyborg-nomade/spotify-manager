"""Protect CLI client-event ownership and the original constructor error boundary."""

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from unittest.mock import Mock

import pytest

from spotify_manager import main
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.interfaces.operations import scrobble_history
from spotify_manager.routines.scrobble_history import ScrobbleHistorySummary


class EmittingClient(LastFmClient):
    """Emit a fixture event during the original no-network constructor stage.

    Args:
        api_key: Validated fixture credential.
        username: Validated fixture account.
        event_callback: Explicit command-owned terminal sink.
    """

    def __init__(
        self, api_key: str, username: str, *, event_callback: Callable[[str], None]
    ) -> None:
        """Initialize the original reader and observe its bound message sink.

        Args:
            api_key: Validated fixture credential.
            username: Validated fixture account.
            event_callback: Explicit command-owned terminal sink.
        """
        super().__init__(api_key, username, event_callback=event_callback)
        event_callback("Fixture client event")


class FailingClient(LastFmClient):
    """Expose construction errors before the original refresh-error boundary.

    Args:
        api_key: Validated fixture credential.
        username: Validated fixture account.
        event_callback: Command-owned terminal sink, not invoked here.
    """

    def __init__(
        self, api_key: str, username: str, *, event_callback: Callable[[str], None]
    ) -> None:
        """Reject construction without running a refresh.

        Args:
            api_key: Validated fixture credential.
            username: Validated fixture account.
            event_callback: Original command-owned sink.

        Raises:
            ValueError: Fixture constructor fails before the refresh starts.
        """
        raise ValueError("Fixture constructor failure")


def _configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LASTFM_API_KEY", "fixture-key")
    monkeypatch.setenv("LASTFM_USERNAME", "fixture-user")


def _summary() -> ScrobbleHistorySummary:
    return ScrobbleHistorySummary(
        checked_at=datetime(2026, 9, 24, tzinfo=UTC),
        username="fixture-user",
        history=(),
        export_scrobbles=0,
        legacy_scrobbles_added=0,
        live_scrobbles_added=0,
        dry_run=True,
        persisted=False,
        backup_path=None,
    )


def test_client_events_reach_original_command_console_and_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep the event channel and flags when the history adapter owns the callback.

    Args:
        monkeypatch: Scoped reader, routine and safe credential replacements.
        capsys: Original command terminal output observation.
    """
    _configuration(monkeypatch)
    refresh = Mock(return_value=_summary())
    monkeypatch.setattr(main, "LastFmClient", EmittingClient)
    monkeypatch.setattr(scrobble_history, "refresh_scrobble_history", refresh)
    main.update_scrobble_history_command(full_rebuild=True, dry_run=True)
    output = capsys.readouterr().out
    assert "Fixture client event" in output
    assert "Last.fm scrobble history" in output
    assert "Dry run: the canonical history was not changed." in output
    assert refresh.call_count == 1
    assert refresh.call_args.kwargs["full_rebuild"] is True
    assert refresh.call_args.kwargs["dry_run"] is True
    assert refresh.call_args.kwargs["expected_username"] == "fixture-user"


def test_constructor_failure_keeps_original_uncaught_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Do not convert constructor errors into the guarded refresh's Typer exit.

    Args:
        monkeypatch: Scoped failing constructor and safe fixture credentials.
        capsys: Original command terminal output observation.
    """
    _configuration(monkeypatch)
    refresh = Mock()
    monkeypatch.setattr(main, "LastFmClient", FailingClient)
    monkeypatch.setattr(scrobble_history, "refresh_scrobble_history", refresh)
    with pytest.raises(ValueError, match="Fixture constructor failure"):
        main.update_scrobble_history_command(full_rebuild=False, dry_run=True)
    refresh.assert_not_called()
    assert capsys.readouterr().out == ""
