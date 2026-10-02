"""Verify pure original audit-event state transitions independently of log storage."""

from spotify_manager.application.artist_review_state import apply_review_event
from spotify_manager.application.artist_review_values import ArtistReviewState


def test_original_review_event_transitions_retain_pending_plan_order() -> None:
    """Apply original plan, completion, ignored and blank-identity transitions."""
    state = ArtistReviewState(set(), {}, {})
    apply_review_event(state, {})
    unfollow = {"event": "unfollow_planned", "artist_id": " a ", "extra": True}
    move: dict[str, object] = {
        "event": "queue_move_planned",
        "artist_id": "a",
        "target": "two",
    }
    apply_review_event(state, unfollow)
    assert state.pending_unfollows["a"] is unfollow
    apply_review_event(state, move)
    assert state.pending_queue_moves["a"] is move
    apply_review_event(state, {"event": "ignored", "artist_id": "a"})
    assert "a" in state.pending_unfollows
    assert "a" in state.pending_queue_moves
    apply_review_event(state, {"event": "artist_completed", "artist_id": "a"})
    assert state.completed_artist_ids == {"a"}
    assert state.pending_unfollows == {}
    assert state.pending_queue_moves == {}
