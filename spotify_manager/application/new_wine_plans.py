"""Existing durable New Wine plan layouts over typed observations."""

from dataclasses import asdict

from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation


def progression_plan(
    action: str,
    release: ReleaseCandidate,
    target: ReleaseTrack | None,
    current_liked: bool,
    streak: int,
    *,
    next_liked: bool = False,
) -> dict[str, object]:
    """Build the original advance or release-completion plan layout.

    Args:
        action: Accepted transition kind.
        release: Selected release.
        target: Selected replacement, if present.
        current_liked: Source membership observation.
        streak: Streak after the source observation.
        next_liked: Whether advancement skips to a later liked track.

    Returns:
        Original durable fields with their existing defaults and streak behavior.
    """
    return {
        "action": action,
        "release": asdict(release),
        "target": asdict(target) if target is not None else None,
        "current_liked": current_liked,
        "consecutive_unliked": streak,
        "next_prior_unliked_streak": 0 if next_liked else streak,
        "album_liked_tracks": None,
        "album_total_tracks": None,
        "should_unsave": False,
        "album_unsaved": False,
        "advance_reason": "next_liked_track" if next_liked else None,
        "drop_reason": None,
    }


def drop_plan(
    release: ReleaseCandidate,
    evaluation: AlbumEvaluation,
    *,
    current_liked: bool,
    consecutive_unliked: int,
    reason: str,
) -> dict[str, object]:
    """Build the original drop plan with its live keep decision.

    Args:
        release: Release being dropped from progression.
        evaluation: Live album evaluation.
        current_liked: Source membership observation.
        consecutive_unliked: Streak after the source observation.
        reason: Existing drop reason identifier.

    Returns:
        Durable drop plan retaining evaluation, unsave intent and original field names.
    """
    return {
        "action": "drop",
        "release": asdict(release),
        "target": None,
        "current_liked": current_liked,
        "consecutive_unliked": consecutive_unliked,
        "album_liked_tracks": evaluation.liked_tracks,
        "album_total_tracks": evaluation.total_tracks,
        "should_unsave": evaluation.decision == "remove",
        "evaluation": evaluation.model_dump(mode="json"),
        "album_unsaved": False,
        "drop_reason": reason,
    }


def record_evaluation(plan: dict[str, object], evaluation: AlbumEvaluation) -> None:
    """Store the live Sauvignon keep decision in the existing durable plan.

    Args:
        plan: Mutable plan whose evaluation was just observed.
        evaluation: Original validated live evaluation.
    """
    plan.update(
        {
            "album_liked_tracks": evaluation.liked_tracks,
            "album_total_tracks": evaluation.total_tracks,
            "should_save": evaluation.decision == "keep",
            "evaluation": evaluation.model_dump(mode="json"),
        }
    )
