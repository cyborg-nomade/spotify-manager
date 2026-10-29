"""Tests for the Palace of Memory CLI command."""

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from spotify_manager import main
from tests.support.feature_invocation import FeatureInvocation


def test_fill_palace_dry_run_uses_configured_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI should expose refresh details and the ten-album preview."""
    received: dict[str, object] = {}
    album = main.palace_of_memory.SpotifyAlbum(
        spotify_id="album-id",
        uri="spotify:album:album-id",
        artist="Artist",
        album="Album",
        saved=True,
        similarity=1.0,
    )
    track = main.palace_of_memory.SpotifyFirstTrack(
        spotify_id="track-id", uri="spotify:track:track-id", name="Opening Track"
    )
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                palace_of_memory_playlist="https://open.spotify.com/playlist/palace"
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    scenario = FillPalaceDryRunUsesConfiguredPlaylistScenario(
        album=album, received=received, track=track
    )
    monkeypatch.setattr(
        main.palace_of_memory,
        "fill_palace_of_memory",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    result = CliRunner().invoke(
        main.app,
        [
            "fill-palace-of-memory",
            "--dry-run",
            "--alphabetical-start",
            "Artist - Album",
        ],
    )
    assert result.exit_code == 0
    assert received == {
        "playlist_id": "palace",
        "dry_run": True,
        "alphabetical_start": "Artist - Album",
        "retry_call": True,
    }
    assert "Saved albums updated: 3970 -> 3971" in result.output
    assert "Palace of Memory" in result.output
    assert "Opening Track" in result.output
    assert "2025-12-31" in result.output
    assert "Alphabetical cursor (manual)" in result.output
    assert "preview only" in result.output


def test_fill_palace_can_only_persist_the_alphabetical_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cursor-only mode should not require or touch the Palace playlist."""
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    scenario = FillPalaceCanOnlyPersistTheAlphabeticalCursorScenario(received=received)
    monkeypatch.setattr(
        main.palace_of_memory,
        "set_alphabetical_cursor",
        AsyncMock(side_effect=scenario.set_cursor),
    )
    monkeypatch.setattr(
        main.palace_of_memory,
        "fill_palace_of_memory",
        FeatureInvocation(
            Mock(side_effect=AssertionError("the playlist routine must not run")),
            ("playlist_id",),
        ),
    )
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(side_effect=AssertionError("playlist configuration must not be loaded")),
    )
    result = CliRunner().invoke(
        main.app, ["fill-palace-of-memory", "--set-alphabetical-cursor", "250"]
    )
    assert result.exit_code == 0
    assert received == {"position": 250, "retry_call": True}
    assert "Saved albums already current: 3983 -> 3983" in result.output
    assert "Alphabetical cursor set to 250" in result.output
    assert "Cursor Artist - Cursor Album" in result.output
    assert "playlist was not changed" in " ".join(result.output.split())


@dataclass
class FillPalaceDryRunUsesConfiguredPlaylistScenario:
    """Retain the original fill palace dry run uses configured playlist fixture.

    Args:
        album: Original album observation or resource.
        received: Original received observation or resource.
        track: Original track observation or resource.
    """

    album: main.palace_of_memory.SpotifyAlbum
    received: dict[str, object]
    track: main.palace_of_memory.SpotifyFirstTrack

    def __call__(
        self, _spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> main.palace_of_memory.PalaceOfMemorySummary:
        """Execute the original fill mock boundary.

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
            alphabetical_start=kwargs["alphabetical_start"],
            retry_call=callable(getattr(kwargs["retry_call"], "attempts", None)),
        )
        return main.palace_of_memory.PalaceOfMemorySummary(
            generated_at=datetime(2026, 8, 4, 10, 47, 52, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            cutoff_date=date(2025, 12, 31),
            available_dates=6000,
            alphabetical_start_index=0,
            alphabetical_next_index=5,
            alphabetical_cursor_overridden=True,
            playlist_length_before=0,
            playlist_length_after=1,
            album_refresh=main.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3970,
                current=3971,
                added=1,
                removed=0,
                skipped=0,
                persisted=True,
                backup_path="/tmp/albums-backup.json",
            ),
            results=(
                main.palace_of_memory.PalaceAlbumResult(
                    source="alphabetical",
                    artist="Artist",
                    album="Album",
                    spotify_album=self.album,
                    first_track=self.track,
                    action="added",
                ),
            ),
        )


@dataclass
class FillPalaceCanOnlyPersistTheAlphabeticalCursorScenario:
    """Retain the original fill palace can only persist the alphabetical cursor fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def set_cursor(
        self, _spotify: Any, position: Any, **kwargs: Any
    ) -> main.palace_of_memory.AlphabeticalCursorUpdate:
        """Execute the original set cursor mock boundary.

        Args:
            _spotify: Original external mock argument.
            position: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            position=position,
            retry_call=callable(getattr(kwargs["retry_call"], "attempts", None)),
        )
        return main.palace_of_memory.AlphabeticalCursorUpdate(
            next_index=249,
            next_album=main.palace_of_memory.YourLibraryAlbum(
                artist="Cursor Artist",
                album="Cursor Album",
                uri="spotify:album:cursor-album",
            ),
            album_refresh=main.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3983,
                current=3983,
                added=0,
                removed=0,
                skipped=0,
                persisted=False,
                backup_path=None,
            ),
        )
