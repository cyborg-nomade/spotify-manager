"""Replay original durable artist-review decisions without inferring new work."""

from spotify_manager.application.artist_review_values import ArtistReviewState


def apply_review_event(state: ArtistReviewState, event: dict[str, object]) -> None:
    """Apply the original audit-log progress semantics in encounter order.

    Args:
        state: Original mutable replayed progress.
        event: Original decoded audit object, preserving native boundary failures.
    """
    identity = str(event.get("artist_id") or "").strip()
    if not identity:
        return
    name = event.get("event")
    if name == "unfollow_planned":
        state.pending_unfollows[identity] = event
    elif name == "queue_move_planned":
        state.pending_queue_moves[identity] = event
    elif name == "artist_completed":
        state.completed_artist_ids.add(identity)
        state.pending_unfollows.pop(identity, None)
        state.pending_queue_moves.pop(identity, None)
