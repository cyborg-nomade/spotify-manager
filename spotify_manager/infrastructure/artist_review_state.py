"""Retain original shallow review checkpoint validation and mutable reconstruction."""

from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.domain.artist_review_values import ArtistReviewError


def default_state() -> dict[str, object]:
    """Build original empty durable progress.

    Returns:
        Original four-field checkpoint.
    """
    return {
        "version": 1,
        "completed_artist_ids": [],
        "pending_unfollows": {},
        "pending_queue_moves": {},
    }


def validate_state(raw: object) -> dict[str, object]:
    """Retain original shallow guards and every unknown checkpoint field.

    Args:
        raw: Original untrusted complete checkpoint.

    Returns:
        Original same mutable valid checkpoint.

    Raises:
        ArtistReviewError: An original version or progress container is invalid.
    """
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ArtistReviewError("Artist-review state is invalid.")
    completed = raw.get("completed_artist_ids")
    if not isinstance(completed, list) or not all(
        isinstance(item, str) for item in completed
    ):
        raise ArtistReviewError("Artist-review state is invalid.")
    if not isinstance(raw.get("pending_unfollows"), dict) or not isinstance(
        raw.get("pending_queue_moves"), dict
    ):
        raise ArtistReviewError("Artist-review state is invalid.")
    return raw


def serialize_state(state: ArtistReviewState) -> dict[str, object]:
    """Retain original sorted completion and same pending-plan dictionaries.

    Args:
        state: Original mutable invocation progress.

    Returns:
        Original four-field durable record.
    """
    return {
        "version": 1,
        "completed_artist_ids": sorted(state.completed_artist_ids),
        "pending_unfollows": state.pending_unfollows,
        "pending_queue_moves": state.pending_queue_moves,
    }


def deserialize_state(raw: object) -> ArtistReviewState:
    """Reconstruct original valid state while discarding non-object pending plans.

    Args:
        raw: Original untrusted complete checkpoint.

    Returns:
        Original mutable progress with unchanged shallow filtering.

    Raises:
        ArtistReviewError: Original checkpoint cannot be validated.
    """
    normalized = validate_state(raw)
    completed = normalized["completed_artist_ids"]
    unfollows = normalized["pending_unfollows"]
    moves = normalized["pending_queue_moves"]
    assert isinstance(completed, list)
    assert isinstance(unfollows, dict)
    assert isinstance(moves, dict)
    return ArtistReviewState(set(completed), _plans(unfollows), _plans(moves))


def _plans(raw: dict[object, object]) -> dict[str, dict[str, object]]:
    plans = {}
    for identity, value in raw.items():
        if isinstance(value, dict):
            plans[str(identity)] = value
    return plans
