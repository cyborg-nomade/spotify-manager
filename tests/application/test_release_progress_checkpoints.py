"""Protect artist and preview-learning checkpoints at accepted effects."""

from typing import cast

import pytest

from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.application.release_progress import ReleaseProgress
from tests.support.release_run import ARTIST
from tests.support.release_run import EffectFailureError
from tests.support.release_run import Effects
from tests.support.release_run import opening


def test_invalid_completed_artists_fail_before_destination_observations() -> None:
    """Reject malformed active progress before any external read or accepted write."""
    context = opening("album")
    context.active["completed_artist_keys"] = "invalid"
    effects = Effects("album")
    with pytest.raises(ReleaseCheckStateError, match="progress is invalid"):
        ReleaseProgress(context, effects, False)
    assert effects.events == []


def test_state_sections_are_retrieved_before_their_types_are_asserted() -> None:
    """Preserve the original missing-section error ahead of earlier malformed types."""
    context = opening("album")
    context.state["artist_mappings"] = None
    del context.state["pending_singles"]
    with pytest.raises(KeyError, match="pending_singles"):
        ReleaseProgress(context, Effects("album"), False)


def test_completed_artist_checkpoint_is_batched_at_original_interval() -> None:
    """Save completion exactly at the configured boundary, preserving unknown fields."""
    context = opening("album")
    effects = Effects("album")
    progress = ReleaseProgress(context, effects, False, interval=2)
    progress.complete(context.artists[0])
    assert not effects.saves and progress.completed_changes == 1
    progress.complete(context.artists[0])
    assert len(effects.saves) == 1 and progress.completed_changes == 0
    assert effects.saves[0]["operator_field"] == {"retain": "unknown"}


def test_completed_checkpoint_failure_retains_accepted_state_and_pending_counter() -> (
    None
):
    """An accepted checkpoint failure prevents the later batching reset."""
    context = opening("album")
    effects = Effects("album", failure="persist")
    progress = ReleaseProgress(context, effects, False, interval=1)
    with pytest.raises(EffectFailureError, match="persist"):
        progress.complete(context.artists[0])
    assert progress.completed_changes == 1
    assert cast(ReleaseState, effects.persisted["active_run"])[
        "completed_artist_keys"
    ] == ["artist"]


def test_preview_mapping_checkpoint_is_independent_of_working_release_state() -> None:
    """Batch learned mappings without saving preview release decisions."""
    context = opening("album")
    effects = Effects("album")
    progress = ReleaseProgress(context, effects, True, interval=2)
    progress.remember_mapping(context.artists[0], ARTIST)
    assert not effects.saves and progress.learned_changes == 1
    progress.remember_mapping(context.artists[0], ARTIST)
    assert len(effects.saves) == 1 and progress.learned_changes == 0
    assert effects.saves[0]["processed_releases"] == {}


@pytest.mark.parametrize(
    "pending,force,saved",
    [
        (0, True, False),
        (1, False, False),
        (-1, False, False),
        (-1, True, True),
        (100, False, True),
    ],
)
def test_preview_learning_flush_preserves_original_nonzero_rules(
    pending: int, force: bool, saved: bool
) -> None:
    """Preserve forced nonzero flushes and the original numeric batching boundary.

    Args:
        pending: Original unflushed changes.
        force: Original forced-flush flag.
        saved: Whether the original checkpoint is due.
    """
    effects = Effects("album")
    progress = ReleaseProgress(opening("album"), effects, True, learned_changes=pending)
    progress.flush_learning(force)
    assert bool(effects.saves) is saved
    assert progress.learned_changes == (0 if saved else pending)
