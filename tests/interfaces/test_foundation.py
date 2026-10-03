"""Run the Foundation use cases through real CLI commands and interaction adapters."""

from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.application.artist_follows import ArtistFollowOutcome
from spotify_manager.application.artist_follows import ArtistPersistenceResult
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.interfaces.operations import (
    recover_removed_albums as recovery_operations,
)
from spotify_manager.interfaces.presenters.album_limits import AlbumReviewPresenter
from spotify_manager.interfaces.presenters.album_limits import present_artist_follow
from spotify_manager.interfaces.presenters.album_limits import read_action
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import recover_removed_albums as recovery
from tests.application.test_album_limits import _album
from tests.application.test_album_limits import _evaluation
from tests.characterization.scenarios import _review_files
from tests.characterization.test_recovery_traces import _files
from tests.routines.test_recover_removed_albums import FakeSpotify as RecoverySpotify
from tests.routines.test_review_album_limits import FakeSpotify as ReviewSpotify


def _today(_value: date | None) -> date:
    return date(2026, 7, 14)


@dataclass
class Choices:
    """Deterministic original-format interface responses.

    Args:
        values: Responses delivered in their original order.
    """

    values: deque[str]

    def read(self, album: YourLibraryAlbum, evaluation: AlbumEvaluation) -> str:
        """Read the next scripted raw action.

        Args:
            album: Current library item.
            evaluation: Assessment shown with the prompt.

        Returns:
            Next unnormalized action.
        """
        return self.values.popleft()


def test_review_cli_executes_follow_prompt_removal_and_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise the real command through composition and the application use case.

    Args:
        monkeypatch: Isolated dependencies and file paths.
        tmp_path: Synthetic mirror and history directory.
    """
    _review_files(monkeypatch, tmp_path)
    spotify = ReviewSpotify(saved_tracks={"t1"})
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    result = CliRunner().invoke(
        main.app, ["review-album-limits", "--no-cache"], input="r\n"
    )
    assert result.exit_code == 0, result.output
    assert spotify.followed == [["art1"]]
    assert spotify.deleted == [["alb1"]]
    assert "Removed: OK Computer - Radiohead" in result.output
    assert "Removed: 1. Followed artists: 1." in result.output


@pytest.mark.parametrize("dry_run", [False, True])
def test_recovery_cli_executes_original_result_and_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dry_run: bool,
) -> None:
    """Exercise real CLI options, use-case effects, and final result presentation.

    Args:
        monkeypatch: Isolated dependencies, date, and paths.
        tmp_path: Synthetic mirror and history directory.
        dry_run: Whether to preview remote writes.
    """
    _files(monkeypatch, tmp_path)
    recovery.REMOVED_ALBUMS_LOG_PATH.write_text(
        (tmp_path / "removed.jsonl").read_text()
    )
    spotify = RecoverySpotify()
    monkeypatch.setattr(main, "review_client", Mock(return_value=spotify))
    monkeypatch.setattr(recovery_operations, "_today", _today)
    arguments = ["recover-removed-albums", "--limit", "1"]
    if dry_run:
        arguments.append("--dry-run")
    result = CliRunner().invoke(main.app, arguments)
    assert result.exit_code == 0, result.output
    assert spotify.saved_album_batches == ([] if dry_run else [["future"]])
    assert spotify.followed_batches == ([] if dry_run else [["guest"]])
    assert "Restored: 1." in result.output


@pytest.mark.parametrize(
    "raw,decision,expected",
    [
        (" r ", "keep", "remove"),
        ("", "remove", "remove"),
        (" K ", "remove", "keep"),
        ("", "keep", "skip"),
        (" S ", "remove", "skip"),
        (" Q ", "remove", "quit"),
    ],
)
def test_original_action_normalization(raw: str, decision: str, expected: str) -> None:
    """Retain whitespace, aliases, and decision-sensitive default actions.

    Args:
        raw: Original user response.
        decision: Current assessment.
        expected: Normalized action.
    """
    choices = Choices(deque([raw]))
    messages: list[str] = []
    assert (
        read_action(_album(), _evaluation(decision), choices.read, messages.append)
        == expected
    )
    assert messages == []


def test_details_and_invalid_actions_repeat_original_prompt() -> None:
    """Details preserve track order and malformed actions re-prompt without a choice."""
    choices = Choices(deque(["d", "invalid", "keep"]))
    messages: list[str] = []
    result = read_action(_album(), _evaluation(), choices.read, messages.append)
    assert result == "keep"
    assert messages == [
        "  01. [not liked] Track",
        "Choose r/remove, k/keep, s/skip, d/details, or q/quit.",
    ]


def test_missing_track_ids_present_original_confirmation_message() -> None:
    """Unknown live membership retains its explicit confirmation prompt."""
    messages: list[str] = []
    presenter = AlbumReviewPresenter(Choices(deque()).read, messages.append, None)
    presenter.show_live_likes(None)
    assert messages == ["Live liked tracks: unavailable; asking for confirmation."]


@pytest.mark.parametrize(
    "persistence,expected",
    [
        (ArtistPersistenceResult(False, False), ["Followed artist: Artist"]),
        (
            ArtistPersistenceResult(True, False),
            [
                "Followed artist: Artist",
                "Recorded artist in artists_total.json: Artist",
            ],
        ),
    ],
)
def test_artist_publication_messages_match_completed_effects(
    persistence: ArtistPersistenceResult,
    expected: list[str],
) -> None:
    """Do not announce statistics publication when it was skipped.

    Args:
        persistence: Completed mirror/statistics outcomes.
        expected: Original messages for those outcomes.
    """
    messages: list[str] = []
    outcome = ArtistFollowOutcome(
        "followed", AlbumArtist("artist", "Artist"), persistence
    )
    present_artist_follow(outcome, _album(), messages.append)
    assert messages == expected


def test_unresolved_artist_message_uses_original_album_credit() -> None:
    """Failed identity resolution remains visible without a false follow message."""
    messages: list[str] = []
    present_artist_follow(
        ArtistFollowOutcome("unresolved", None), _album(), messages.append
    )
    assert messages == ["Could not resolve artist id for: Artist"]
