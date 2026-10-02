"""Queue 3 durable records retain original constructor and coercion rules."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import cast

from spotify_manager.application.catalog_records import DiscographyRecord
from spotify_manager.application.catalog_records import ReleaseRecord
from spotify_manager.application.catalog_records import TrackRecord
from spotify_manager.application.queue_3_values import FlushAction
from spotify_manager.application.queue_3_values import FlushResult
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation


def source_from_record(raw: object) -> PlaylistTrack:
    """Reconstruct a source using the existing dictionary and constructor checks.

    Args:
        raw: Serialized source record.

    Returns:
        Source marker retaining the original coercions and release fields.

    Raises:
        Queue3StateError: Source or release is not a mapping.
        TypeError: Release constructor fields are missing or unexpected.
        KeyError: A required source field is absent.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise Queue3StateError("Queue 3 run has an invalid source track.")
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
        Queue3StateError: The non-null record is not a mapping.
        TypeError: Constructor fields are missing or unexpected.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise Queue3StateError("Queue 3 plan has an invalid release.")
    return DiscographyRelease(**cast(DiscographyRecord, raw))


def track_from_record(raw: object) -> ReleaseTrack | None:
    """Reconstruct an optional target without tightening legacy validation.

    Args:
        raw: Serialized target or None.

    Returns:
        Target track, or None when the plan has no target.

    Raises:
        Queue3StateError: The non-null record is not a mapping.
        TypeError: Constructor fields are missing or unexpected.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise Queue3StateError("Queue 3 plan has an invalid target track.")
    return ReleaseTrack(**cast(TrackRecord, raw))


def result_from_plan(
    source: PlaylistTrack,
    plan: dict[str, object],
    *,
    artist_name: str,
    dry_run: bool,
) -> FlushResult:
    """Convert one durable plan using the original coercions and optional fields.

    Args:
        source: Snapshotted original marker.
        plan: Durable plan, retaining tolerance of unknown actions and fields.
        artist_name: Logical artist display name.
        dry_run: Whether this is a preview.

    Returns:
        Original public transition result.

    Raises:
        Queue3StateError: A target or release record is not a mapping.
        TypeError: Saved constructor fields are missing or unexpected.
        ValidationError: A stored evaluation is invalid.
        KeyError: The action is missing.
    """
    action = str(plan["action"])
    target = track_from_record(plan.get("target"))
    target_release = release_from_record(plan.get("target_release"))
    evaluation = (
        AlbumEvaluation.model_validate(plan["evaluation"])
        if isinstance(plan.get("evaluation"), dict)
        else None
    )
    public_action = {
        "composer_advance": "composer playlist",
        "next_release": "next release",
    }.get(action, action)
    return FlushResult(
        artist=artist_name,
        source_track=source.name,
        source_release=source.release.name,
        action=cast(FlushAction, public_action),
        target_track=target.name if target is not None else None,
        target_release=target_release.name if target_release is not None else None,
        album_decision=evaluation.decision if evaluation is not None else None,
        album_liked_tracks=evaluation.liked_tracks if evaluation is not None else None,
        album_total_tracks=evaluation.total_tracks if evaluation is not None else None,
        composer_playlist=(
            str(plan["composer_playlist_name"])
            if plan.get("composer_playlist_name")
            else None
        ),
        reason=str(plan["reason"]) if plan.get("reason") else None,
        dry_run=dry_run,
    )


def new_run(
    playlist_id: str,
    tracks: list[PlaylistTrack],
    state: dict[str, object],
    now: Callable[[], datetime],
    limit: int,
) -> dict[str, object]:
    """Snapshot the first distinct logical artists before reading separate timestamps.

    Args:
        playlist_id: Queue 3 destination identifier.
        tracks: Live queue markers, including projected annual additions.
        state: Complete namespace containing original composer route records.
        now: Clock read separately for run identity and creation time.
        limit: Existing daily artist cap.

    Returns:
        Original active run with pending, unplanned artist entries.

    Raises:
        KeyError: The composer routes container is missing.
    """
    routes = cast(dict[str, object], state["composer_routes"])
    selected = _selected(tracks, _route_index(routes), limit)
    return {
        "run_id": now().strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "created_at": now().isoformat(),
        "entries": _entries(selected),
    }


def _route_index(routes: dict[str, object]) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    for artist_id, raw in routes.items():
        if not isinstance(raw, dict):
            continue
        track_id = str(raw.get("current_track_id") or "")
        name = str(raw.get("artist_name") or "")
        if track_id and name:
            index[track_id] = (artist_id, name)
    return index


def _selected(
    tracks: list[PlaylistTrack],
    routes: dict[str, tuple[str, str]],
    limit: int,
) -> list[tuple[PlaylistTrack, str, str]]:
    selected: list[tuple[PlaylistTrack, str, str]] = []
    seen: set[str] = set()
    for track in tracks:
        artist_id, name = routes.get(
            track.spotify_id, (track.primary_artist_id, track.primary_artist_name)
        )
        if artist_id in seen:
            continue
        selected.append((track, artist_id, name))
        seen.add(artist_id)
        if len(selected) == limit:
            break
    return selected


def _entries(selected: list[tuple[PlaylistTrack, str, str]]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for track, artist_id, name in selected:
        entries.append(
            {
                "source": asdict(track),
                "artist_id": artist_id,
                "artist_name": name,
                "status": "pending",
                "plan": None,
            }
        )
    return entries
