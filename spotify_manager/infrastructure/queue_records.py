"""Decode original tolerant Queue records at the untyped JSON constructor boundary."""

from typing import Any
from typing import cast

from spotify_manager.application.queue_flush_values import FlushAction
from spotify_manager.application.queue_flush_values import FlushResult
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.discovery import CatalogTrack


# JSON constructor fields retain the original permissive dataclass values.
type ConstructorFields = dict[str, Any]


def mapped_artist(raw: object) -> SpotifyArtistCandidate | None:
    """Decode original artist mappings without introducing value validation.

    Args:
        raw: Original unchecked JSON mapping.

    Returns:
        Original constructed mapping or no mapping on shape failure.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return SpotifyArtistCandidate(**cast(ConstructorFields, raw))
    except TypeError:
        return None


def playlist_track(raw: object) -> PlaylistTrack:
    """Decode the original stored source fields and nested release.

    Args:
        raw: Original unchecked JSON source.

    Returns:
        Original constructed authoritative source marker.

    Raises:
        QueueStateError: Original source shape cannot be constructed.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise QueueStateError("Queue run contains an invalid playlist track.")
    try:
        return PlaylistTrack(
            spotify_id=str(raw["spotify_id"]),
            uri=str(raw["uri"]),
            name=str(raw["name"]),
            primary_artist_id=str(raw["primary_artist_id"]),
            primary_artist_name=str(raw["primary_artist_name"]),
            release=ReleaseCandidate(**cast(ConstructorFields, raw["release"])),
        )
    except (KeyError, TypeError) as exc:
        raise QueueStateError("Queue run contains an invalid playlist track.") from exc


def catalog_track(raw: object) -> CatalogTrack | None:
    """Decode the original optional target without strengthening value validation.

    Args:
        raw: Original unchecked JSON target.

    Returns:
        Original constructed target or no target.

    Raises:
        QueueStateError: Original target shape cannot be constructed.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QueueStateError("Queue plan contains an invalid target track.")
    try:
        return CatalogTrack(**cast(ConstructorFields, raw))
    except TypeError as exc:
        raise QueueStateError("Queue plan contains an invalid target track.") from exc


def _integer_fields(plan: dict[str, object]) -> dict[str, int]:
    fields: dict[str, int] = {}
    for key in ("top_tracks", "top_liked_tracks", "total_liked_tracks"):
        value = plan.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise QueueStateError(f"Queue plan has invalid {key}.")
        fields[key] = value
    return fields


def flush_result(
    source: PlaylistTrack, plan: dict[str, object], preview: bool
) -> FlushResult:
    """Construct the original completion result after target and count validation.

    Args:
        source: Original authoritative source marker.
        plan: Original accepted raw plan.
        preview: Original preview behavior.

    Returns:
        Original completion fields, including legacy string coercions.

    Raises:
        QueueStateError: Original target or count fields cannot be decoded.
        KeyError: Original required action is absent.
    """
    target = catalog_track(plan.get("target"))
    counts = _integer_fields(plan)
    return FlushResult(
        artist=source.primary_artist_name,
        source_track=source.name,
        action=cast(FlushAction, str(plan["action"])),
        top_tracks=counts["top_tracks"],
        top_liked_tracks=counts["top_liked_tracks"],
        total_liked_tracks=counts["total_liked_tracks"],
        target_track=target.name if target is not None else None,
        target_release=str(plan["target_release"])
        if plan.get("target_release")
        else None,
        reason=str(plan.get("reason") or "") or None,
        dry_run=preview,
    )
