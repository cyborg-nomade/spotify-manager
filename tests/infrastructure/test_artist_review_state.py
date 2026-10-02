"""Verify original shallow checkpoints, durable replay and native log failures."""

import json
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.infrastructure.artist_review_files import load_review_state
from spotify_manager.infrastructure.artist_review_state import default_state
from spotify_manager.infrastructure.artist_review_state import deserialize_state
from spotify_manager.infrastructure.artist_review_state import serialize_state
from spotify_manager.infrastructure.artist_review_state import validate_state


Raw = dict[str, object]


def _cases(name: str) -> list[Raw]:
    path = Path(__file__).resolve().parents[1] / f"fixtures/refactor/{name}.json"
    return cast(list[Raw], json.loads(path.read_text()))


def _checkpoint(raw: object) -> Raw:
    try:
        validated = validate_state(raw)
        assert validated is raw
        state = deserialize_state(validated)
        return {"state": serialize_state(state), "validated": validated}
    except ArtistReviewError as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@pytest.mark.parametrize("case", _cases("artist_review_state"))
def test_review_checkpoint_retains_original_shallow_validation(case: Raw) -> None:
    """Keep boolean versions, unknown fields, sorted completion and pending filtering.

    Args:
        case: Immutable original untrusted checkpoint and observations.
    """
    assert json.loads(json.dumps(_checkpoint(case["raw"]))) == case["outcome"]


@pytest.mark.parametrize("case", _cases("artist_review_log"))
def test_review_log_retains_original_replay_and_native_errors(
    tmp_path: Path, case: Raw
) -> None:
    """Ignore torn/blank lines while preserving native valid non-object failures.

    Args:
        tmp_path: Isolated original legacy audit location.
        case: Immutable original audit bytes and replayed observations.
    """
    path = tmp_path / "progress.jsonl"
    if case["text"] is not None:
        path.write_text(cast(str, case["text"]))
    result: Raw
    try:
        result = {"state": serialize_state(load_review_state(path))}
    except (AttributeError, TypeError) as exc:
        result = {"error": type(exc).__name__, "message": str(exc)}
    assert result == case["outcome"]


def test_default_review_state_matches_the_original_empty_checkpoint() -> None:
    """Retain the original four default fields and independently allocated plans."""
    original = default_state()
    assert original == {
        "version": 1,
        "completed_artist_ids": [],
        "pending_unfollows": {},
        "pending_queue_moves": {},
    }
    assert original is not default_state()
