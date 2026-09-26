"""Existing Slow Listening state records and their tolerant reconstruction rules."""

from dataclasses import asdict
from typing import TypedDict
from typing import cast

from spotify_manager.application.slow_listening_values import FlushAction
from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack


class ReleaseRecord(TypedDict):
    """Existing serialized release fields used at the durable state boundary."""

    spotify_id: str
    uri: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_id: str
    primary_artist_name: str


class DiscographyRecord(ReleaseRecord):
    """Selected-edition fields retained alongside the original release fields."""

    chronology_date: str
    identity: str
    saved: bool
    plain: bool
    edition_rank: int


class TrackRecord(TypedDict):
    """Existing ordered-track fields stored in a durable transition plan."""

    spotify_id: str
    uri: str
    name: str
    disc_number: int
    track_number: int


def source_from_record(raw: object) -> PlaylistTrack:
    """Reconstruct a source using the existing dictionary and constructor checks.

    Args:
        raw: Serialized source record.

    Returns:
        Source marker retaining the original coercions and release fields.

    Raises:
        SlowListeningStateError: Source or release is not a mapping.
        TypeError: Release constructor fields are missing or unexpected.
        KeyError: A required source field is absent.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise SlowListeningStateError("Slow Listening run has an invalid source.")
    release = ReleaseCandidate(**cast(ReleaseRecord, raw["release"]))
    return PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=release,
    )


def release_from_record(raw: object) -> DiscographyRelease | None:
    """Reconstruct an optional selected edition without tightening validation.

    Args:
        raw: Serialized release or None.

    Returns:
        The selected release, or None when no release was saved.

    Raises:
        SlowListeningStateError: The non-null record is not a mapping.
        TypeError: Constructor fields are missing or unexpected.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening run has an invalid release.")
    return DiscographyRelease(**cast(DiscographyRecord, raw))


def track_from_record(raw: object) -> ReleaseTrack | None:
    """Reconstruct an optional target without tightening legacy validation.

    Args:
        raw: Serialized target or None.

    Returns:
        Target track, or None when the plan has no target.

    Raises:
        SlowListeningStateError: The non-null record is not a mapping.
        TypeError: Constructor fields are missing or unexpected.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SlowListeningStateError("Slow Listening run has an invalid target.")
    return ReleaseTrack(**cast(TrackRecord, raw))


def result_from_plan(
    source: PlaylistTrack, plan: dict[str, object], *, dry_run: bool
) -> FlushResult:
    """Present a saved plan through the unchanged public result value.

    Args:
        source: Original playlist marker.
        plan: Existing durable plan, retaining unknown fields and actions.
        dry_run: Whether this result is a preview.

    Returns:
        Result with the original filtering and string coercions.

    Raises:
        SlowListeningStateError: A saved target or release is not a mapping.
        TypeError: Saved constructor fields are invalid.
        KeyError: The action is absent.
    """
    target = track_from_record(plan.get("target"))
    release = release_from_record(plan.get("target_release"))
    return FlushResult(
        source_track=source.name,
        source_release=source.release.name,
        artist=source.primary_artist_name,
        action=cast(FlushAction, str(plan["action"])),
        target_track=target.name if target is not None else None,
        target_release=release.name if release is not None else None,
        skipped_candidates=_labels(plan.get("skipped_candidates")),
        reason=str(plan["reason"]) if plan.get("reason") else None,
        dry_run=dry_run,
    )


def _labels(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    labels = []
    for candidate in raw:
        if isinstance(candidate, str):
            labels.append(str(candidate))
    return tuple(labels)


def snapshot_entries(tracks: tuple[PlaylistTrack, ...]) -> list[dict[str, object]]:
    """Snapshot at most two markers using the original entry layout.

    Args:
        tracks: Initial live playlist observations.

    Returns:
        Pending entries with no plan or skipped candidates.
    """
    entries: list[dict[str, object]] = []
    for track in tracks[:2]:
        entries.append(
            {
                "source": asdict(track),
                "status": "pending",
                "plan": None,
                "skipped_candidates": [],
            }
        )
    return entries
