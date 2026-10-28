"""Tests for the New Kids CLI command."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.routines import composer_playlists
from tests.support.feature_invocation import FeatureInvocation


def release() -> main.new_kids.RankedRelease:
    """Build one ranked release for prompt and summary tests."""
    return main.new_kids.RankedRelease(
        spotify_id="release",
        uri="spotify:album:release",
        name="Release",
        release_type="Album",
        release_date="2020-01-01",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        popularity=72,
        top_track_rank=2,
        tier=0,
        identity="RELEASE",
        saved=True,
        plain=True,
    )


def test_new_kids_release_prompt_returns_selected_release(monkeypatch) -> None:
    """The Rich release table should return the selected Spotify id."""
    candidate = release()
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "1")

    choice = main.ask_new_kids_release_choice(
        Console(),
        "Artist",
        (candidate,),
    )

    assert choice == "release"


def test_new_kids_release_prompt_accepts_owned_composer_playlist(
    monkeypatch,
) -> None:
    """The shared picker should also return a selected works playlist id."""
    candidate = composer_playlists.OwnedPlaylist(
        spotify_id="bach-works",
        name="Complete Bach works",
        total_tracks=100,
    )
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "1")

    choice = main.ask_new_kids_release_choice(
        Console(),
        "Johann Sebastian Bach",
        (candidate,),
    )

    assert choice == "bach-works"


def test_flush_new_kids_dry_run_uses_all_configured_playlists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI should parse and pass all five destination/source settings."""
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_kids_on_the_block_playlist="spotify:playlist:new",
                the_queue_2_playlist="spotify:playlist:queue",
                great_discoveries_2026_playlist="spotify:playlist:great",
                unlucky_ones_playlist="spotify:playlist:unlucky",
                discography_newfoundland_playlist="spotify:playlist:newfoundland",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    scenario = FlushNewKidsDryRunUsesAllConfiguredPlaylistsScenario(received=received)
    monkeypatch.setattr(
        main.new_kids,
        "flush_new_kids",
        FeatureInvocation(
            scenario,
            (
                "new_kids_playlist_id",
                "queue_2_playlist_id",
                "great_discoveries_playlist_id",
                "unlucky_ones_playlist_id",
                "newfoundland_playlist_id",
            ),
        ),
    )
    result = CliRunner().invoke(main.app, ["flush-new-kids", "--dry-run"])
    assert result.exit_code == 0
    assert received == {
        "new_playlist": "new",
        "queue_playlist": "queue",
        "great_playlist": "great",
        "unlucky_playlist": "unlucky",
        "newfoundland_playlist": "newfoundland",
        "dry_run": True,
    }
    assert "Current" in result.output
    assert "Next" in result.output
    assert "Queue Artist" in result.output
    assert "Dry run: New Kids 9 -> 10" in result.output


def test_flush_queue_2_dry_run_reports_both_playlist_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Queue 2 CLI should pass configuration and render both list counts."""
    received: dict[str, object] = {}
    monkeypatch.setattr(
        main,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_kids_on_the_block_playlist="spotify:playlist:new",
                the_queue_2_playlist="spotify:playlist:queue",
                great_discoveries_2026_playlist="spotify:playlist:great",
                unlucky_ones_playlist="spotify:playlist:unlucky",
                discography_newfoundland_playlist="spotify:playlist:newfoundland",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "_native_review_client",
        AsyncMock(side_effect=Mock(return_value=object())),
    )
    scenario = FlushQueue2DryRunReportsBothPlaylistTransitionsScenario(
        received=received
    )
    monkeypatch.setattr(
        main.new_kids,
        "flush_queue_2",
        FeatureInvocation(
            scenario,
            (
                "new_kids_playlist_id",
                "queue_2_playlist_id",
                "great_discoveries_playlist_id",
                "unlucky_ones_playlist_id",
                "newfoundland_playlist_id",
            ),
        ),
    )
    result = CliRunner().invoke(main.app, ["flush-queue-2", "--dry-run"])
    assert result.exit_code == 0
    assert received == {
        "new_playlist": "new",
        "queue_playlist": "queue",
        "great_playlist": "great",
        "unlucky_playlist": "unlucky",
        "newfoundland_playlist": "newfoundland",
        "dry_run": True,
    }
    assert "Queue Artist" in result.output
    assert "First Artist" in result.output
    assert "Dry run: New Kids 9 -> 10; Queue 2 20 -> 19" in result.output


@dataclass
class FlushNewKidsDryRunUsesAllConfiguredPlaylistsScenario:
    """Retain the original flush new kids dry run uses all configured playlists fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def __call__(
        self,
        _spotify: Any,
        new_playlist: Any,
        queue_playlist: Any,
        great_playlist: Any,
        unlucky_playlist: Any,
        newfoundland_playlist: Any,
        choice_reader: Any,
        **kwargs: Any,
    ) -> main.new_kids.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _spotify: Original external mock argument.
            new_playlist: Original external mock argument.
            queue_playlist: Original external mock argument.
            great_playlist: Original external mock argument.
            unlucky_playlist: Original external mock argument.
            newfoundland_playlist: Original external mock argument.
            choice_reader: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        assert callable(getattr(choice_reader, "choose", None))
        self.received.update(
            new_playlist=new_playlist,
            queue_playlist=queue_playlist,
            great_playlist=great_playlist,
            unlucky_playlist=unlucky_playlist,
            newfoundland_playlist=newfoundland_playlist,
            dry_run=kwargs["dry_run"],
        )
        return main.new_kids.FlushSummary(
            results=(
                main.new_kids.FlushResult(
                    artist="Artist",
                    source_track="Current",
                    source_release="Release",
                    current_liked=False,
                    consecutive_unliked=1,
                    action="advance",
                    target_track="Next",
                    target_release="Release",
                    dry_run=True,
                ),
            ),
            prefill=(main.new_kids.FillResult("Queue Artist", "Marker", "moved"),),
            postfill=(),
            playlist_length_before=9,
            playlist_length_after=10,
            paused=False,
            resumed=False,
            dry_run=True,
        )


@dataclass
class FlushQueue2DryRunReportsBothPlaylistTransitionsScenario:
    """Retain the original flush queue 2 dry run reports both playlist transitions
    fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def __call__(
        self,
        _spotify: Any,
        new_playlist: Any,
        queue_playlist: Any,
        great_playlist: Any,
        unlucky_playlist: Any,
        newfoundland_playlist: Any,
        choice_reader: Any,
        **kwargs: Any,
    ) -> main.new_kids.Queue2Summary:
        """Execute the original run mock boundary.

        Args:
            _spotify: Original external mock argument.
            new_playlist: Original external mock argument.
            queue_playlist: Original external mock argument.
            great_playlist: Original external mock argument.
            unlucky_playlist: Original external mock argument.
            newfoundland_playlist: Original external mock argument.
            choice_reader: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        assert callable(getattr(choice_reader, "choose", None))
        self.received.update(
            new_playlist=new_playlist,
            queue_playlist=queue_playlist,
            great_playlist=great_playlist,
            unlucky_playlist=unlucky_playlist,
            newfoundland_playlist=newfoundland_playlist,
            dry_run=kwargs["dry_run"],
        )
        return main.new_kids.Queue2Summary(
            results=(
                main.new_kids.FlushResult(
                    artist="Queue Artist",
                    source_track="Current",
                    source_release="Release",
                    current_liked=True,
                    consecutive_unliked=0,
                    action="advance",
                    target_track="Next",
                    target_release="Release",
                    dry_run=True,
                ),
            ),
            prefill=(main.new_kids.FillResult("First Artist", "Marker", "moved"),),
            queue_length_before=20,
            queue_length_after=19,
            new_kids_length_before=9,
            new_kids_length_after=10,
            paused=False,
            resumed=False,
            dry_run=True,
        )
