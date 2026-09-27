"""Existing New Wine durable catalog records and public result translation."""

from typing import cast

from spotify_manager.application.catalog_records import ReleaseRecord
from spotify_manager.application.catalog_records import TrackRecord
from spotify_manager.application.new_wine_values import FlushAction
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.new_wine_values import NewWineStateError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack


def source_from_record(raw: object) -> PlaylistTrack:
    """Rebuild one snapshotted source track.

    Args:
        raw: Original serialized marker, including its release record.

    Returns:
        Source with the original string coercions and release constructor behavior.

    Raises:
        NewWineStateError: The marker or nested release is not a record.
        KeyError: A required source field is absent.
        TypeError: The release constructor rejects missing or unknown fields.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise NewWineStateError("New Wine run contains an invalid source track.")
    release = ReleaseCandidate(**cast(ReleaseRecord, raw["release"]))
    return PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=release,
    )


def release_from_record(raw: object) -> ReleaseCandidate:
    """Rebuild a release stored in one durable plan.

    Args:
        raw: Original serialized release.

    Returns:
        Release constructed without additional validation or coercion.

    Raises:
        NewWineStateError: The release is not a record.
        TypeError: The constructor rejects missing or unknown fields.
    """
    if not isinstance(raw, dict):
        raise NewWineStateError("New Wine run contains an invalid release plan.")
    return ReleaseCandidate(**cast(ReleaseRecord, raw))


def track_from_record(raw: object) -> ReleaseTrack | None:
    """Rebuild an optional target track stored in one durable plan.

    Args:
        raw: Original serialized target, or None.

    Returns:
        Original target value, or None when absent.

    Raises:
        NewWineStateError: A non-null target is not a record.
        TypeError: The constructor rejects missing or unknown fields.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise NewWineStateError("New Wine run contains an invalid target track.")
    return ReleaseTrack(**cast(TrackRecord, raw))


def result_from_plan(
    source: PlaylistTrack,
    plan: dict[str, object],
    *,
    dry_run: bool,
    album_unsaved: bool = False,
) -> FlushResult:
    """Convert a durable plan into the public result model.

    Args:
        source: Original marker whose transition completed.
        plan: Original durable plan retaining optional and unknown fields.
        dry_run: Whether the result describes a preview.
        album_unsaved: Accepted or previewed album removal outcome.

    Returns:
        Existing public result with original optional-field coercions.

    Raises:
        NewWineStateError: A saved catalog value is not a record.
        KeyError: A required plan field is absent.
        TypeError: A saved catalog constructor rejects its fields.
    """
    release = release_from_record(plan["release"])
    target = track_from_record(plan.get("target"))
    continuation_release = (
        release_from_record(plan["continuation_release"])
        if plan.get("continuation_release") is not None
        else None
    )
    continuation_target = track_from_record(plan.get("continuation_target"))
    return FlushResult(
        source_track=source.name,
        artist=source.primary_artist_name,
        release=release.name,
        release_type=release.release_type,
        current_liked=bool(plan["current_liked"]),
        consecutive_unliked=cast(int, plan["consecutive_unliked"]),
        action=cast(FlushAction, str(plan["action"])),
        target_track=target.name if target is not None else None,
        album_liked_tracks=(
            cast(int, plan["album_liked_tracks"])
            if plan.get("album_liked_tracks") is not None
            else None
        ),
        album_total_tracks=(
            cast(int, plan["album_total_tracks"])
            if plan.get("album_total_tracks") is not None
            else None
        ),
        album_unsaved=album_unsaved,
        advance_reason=(
            str(plan["advance_reason"])
            if plan.get("advance_reason") is not None
            else None
        ),
        drop_reason=(
            str(plan["drop_reason"]) if plan.get("drop_reason") is not None else None
        ),
        continuation_release=(
            continuation_release.name if continuation_release is not None else None
        ),
        continuation_track=(
            continuation_target.name if continuation_target is not None else None
        ),
        canonical_track_count=(
            cast(int, plan["canonical_track_count"])
            if plan.get("canonical_track_count") is not None
            else None
        ),
        canonical_cutoff_track=(
            str(plan["canonical_cutoff_track"])
            if plan.get("canonical_cutoff_track") is not None
            else None
        ),
        dry_run=dry_run,
    )
