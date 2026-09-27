"""Original durable discovery records and tolerant New Kids/Queue 2 translations."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Literal
from typing import cast

from spotify_manager.application.catalog_records import CatalogTrackRecord
from spotify_manager.application.catalog_records import RankedReleaseRecord
from spotify_manager.application.catalog_records import ReleaseRecord
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_progression import source_release


def positive_int(value: object, fallback: int = 0) -> int:
    """Retain nonnegative integers while rejecting booleans and other values.

    Args:
        value: Original decoded progress/count value.
        fallback: Existing default for invalid values.

    Returns:
        Accepted nonnegative integer, otherwise the supplied fallback.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback


def assessment_from_record(raw: object) -> ArtistAssessment:
    """Rebuild completion criteria using the original tolerant count coercions.

    Args:
        raw: Saved completion assessment.

    Returns:
        Original assessment, retaining iterable reason coercion and track defaults.

    Raises:
        NewKidsStateError: The assessment or a track is not a record.
        TypeError: Reasons are not iterable or a track constructor rejects fields.
    """
    if not isinstance(raw, dict):
        raise NewKidsStateError("Artist completion plan lacks assessment.")
    return ArtistAssessment(
        liked_tracks=positive_int(raw.get("liked_tracks")),
        saved_releases=positive_int(raw.get("saved_releases")),
        total_releases=positive_int(raw.get("total_releases")),
        liked_primary_tracks=positive_int(raw.get("liked_primary_tracks")),
        total_primary_tracks=positive_int(raw.get("total_primary_tracks")),
        qualifies=bool(raw.get("qualifies")),
        reasons=tuple(str(value) for value in raw.get("reasons", [])),
        representative_track=track_from_record(raw.get("representative_track")),
        top_liked_track=track_from_record(raw.get("top_liked_track")),
    )


def source_from_record(raw: object) -> PlaylistTrack:
    """Rebuild one original source snapshot without tightening its constructor rules.

    Args:
        raw: Serialized source with nested release fields.

    Returns:
        Original source value with existing string coercions.

    Raises:
        NewKidsStateError: The source or nested release is not a record.
        KeyError: A required source field is missing.
        TypeError: The release constructor rejects missing or unknown fields.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("release"), dict):
        raise NewKidsStateError("New Kids run contains an invalid source track.")
    return PlaylistTrack(
        spotify_id=str(raw["spotify_id"]),
        uri=str(raw["uri"]),
        name=str(raw["name"]),
        primary_artist_id=str(raw["primary_artist_id"]),
        primary_artist_name=str(raw["primary_artist_name"]),
        release=ReleaseCandidate(**cast(ReleaseRecord, raw["release"])),
    )


def release_from_record(raw: object) -> RankedRelease:
    """Rebuild a saved discovery release using the original constructor boundary.

    Args:
        raw: Serialized ranked release.

    Returns:
        Original ranked release without additional coercion.

    Raises:
        NewKidsStateError: The release is not a record.
        TypeError: The constructor rejects missing or unknown fields.
    """
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids plan contains an invalid release.")
    return RankedRelease(**cast(RankedReleaseRecord, raw))


def track_from_record(raw: object) -> CatalogTrack | None:
    """Rebuild an optional saved primary-credit track.

    Args:
        raw: Serialized track, or None for an absent target.

    Returns:
        Original track value or None, retaining constructor defaults.

    Raises:
        NewKidsStateError: A non-null track is not a record.
        TypeError: The constructor rejects missing or unknown fields.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise NewKidsStateError("New Kids plan contains an invalid track.")
    return CatalogTrack(**cast(CatalogTrackRecord, raw))


def artist_progress(
    state: dict[str, object],
    source: PlaylistTrack,
    artist_id: str,
    artist_name: str,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Create original artist progress when absent and discard obsolete selection keys.

    Args:
        state: Mutable complete namespace.
        source: Original review marker.
        artist_id: Logical artist identifier.
        artist_name: Logical artist display name.
        clock: Original UTC clock, read only when creating progress.

    Returns:
        The mutable artist record within the namespace, retaining unknown fields.

    Raises:
        KeyError: The artist container is missing.
        AssertionError: The artist container is not a record.
    """
    artists = state["artists"]
    assert isinstance(artists, dict)
    raw = artists.get(artist_id)
    if not isinstance(raw, dict):
        release = source_release(source)
        raw = {
            "artist_name": artist_name,
            "current_release_id": release.spotify_id,
            "prior_unliked_streak": None,
            "updated_at": clock().isoformat(),
        }
        artists[artist_id] = raw
    for key in (
        "selected_release_ids",
        "selected_release_identities",
        "completed_release_ids",
    ):
        raw.pop(key, None)
    return cast(dict[str, object], raw)


def logical_artist(state: dict[str, object], track: PlaylistTrack) -> tuple[str, str]:
    """Resolve the first valid logical-composer route matching the current marker.

    Args:
        state: Original namespace, tolerating absent or malformed route containers.
        track: Marker whose performer credit may represent a logical composer.

    Returns:
        First matching nonempty logical credit, otherwise the original primary credit.
    """
    routes = state.get("composer_routes")
    if not isinstance(routes, dict):
        return track.primary_artist_id, track.primary_artist_name
    for artist_id, raw in routes.items():
        name = _route_artist(raw, track.spotify_id)
        if name:
            return str(artist_id), name
    return track.primary_artist_id, track.primary_artist_name


def _route_artist(raw: object, track_id: str) -> str:
    if not isinstance(raw, dict):
        return ""
    if str(raw.get("current_track_id") or "") != track_id:
        return ""
    return str(raw.get("artist_name") or "").strip()


def new_run(
    playlist_id: str,
    tracks: list[PlaylistTrack],
    state: dict[str, object],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Snapshot one marker per logical artist with the original timestamp boundaries.

    Args:
        playlist_id: Review playlist identifier.
        tracks: Original ordered live markers.
        state: Existing logical-composer route observations.
        clock: Original UTC clock read for ID and start time separately.

    Returns:
        Original active-run record with pending unplanned entries.
    """
    entries = _snapshot(tracks, state)
    return {
        "run_id": clock().strftime("%Y%m%dT%H%M%S%fZ"),
        "playlist_id": playlist_id,
        "status": "active",
        "entries": entries,
        "started_at": clock().isoformat(),
    }


def _snapshot(
    tracks: list[PlaylistTrack], state: dict[str, object]
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for track in tracks:
        artist_id, name = logical_artist(state, track)
        if artist_id in seen:
            continue
        seen.add(artist_id)
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


type FlushAction = Literal[
    "advance", "next release", "great discovery", "unlucky", "unfollowed", "skip"
]


def result_from_plan(
    source: PlaylistTrack,
    plan: dict[str, object],
    dry_run: bool,
    *,
    artist_name: str | None = None,
) -> FlushResult:
    """Translate a saved discovery plan into the unchanged public outcome.

    Args:
        source: Original source marker.
        plan: Saved plan, retaining tolerant optional fields and unknown actions.
        dry_run: Whether this result describes a preview.
        artist_name: Optional logical composer name overriding the primary credit.

    Returns:
        Original result with existing count coercions and optional metadata.

    Raises:
        NewKidsStateError: A saved catalog value is not a record.
        KeyError: The required result action is absent.
        TypeError: A catalog constructor rejects its saved fields.
    """
    target = track_from_record(plan.get("target"))
    target_release = (
        release_from_record(plan["target_release"])
        if plan.get("target_release") is not None
        else None
    )
    assessment = plan.get("assessment")
    reasons: tuple[str, ...] = ()
    if isinstance(assessment, dict):
        raw_reasons = assessment.get("reasons")
        if isinstance(raw_reasons, (list, tuple)):
            reasons = tuple(str(reason) for reason in raw_reasons)
    evaluation = plan.get("evaluation")
    liked_tracks: int | None = None
    total_tracks: int | None = None
    decision: str | None = None
    if isinstance(evaluation, dict):
        liked_tracks = positive_int(evaluation.get("liked_tracks"))
        total_tracks = positive_int(evaluation.get("total_tracks"))
        decision = str(evaluation.get("decision") or "") or None
    return FlushResult(
        artist=artist_name or source.primary_artist_name,
        source_track=source.name,
        source_release=source.release.name,
        current_liked=bool(plan.get("current_liked")),
        consecutive_unliked=positive_int(plan.get("consecutive_unliked")),
        action=cast(FlushAction, str(plan["result_action"])),
        target_track=target.name if target else None,
        target_release=target_release.name if target_release else None,
        release_number=(positive_int(plan.get("release_number")) or None),
        album_decision=decision,
        album_liked_tracks=liked_tracks,
        album_total_tracks=total_tracks,
        qualification_reasons=reasons,
        composer_playlist=(
            str(plan.get("composer_playlist_name"))
            if plan.get("composer_playlist_name")
            else None
        ),
        composer_position=(positive_int(plan.get("composer_position")) or None),
        composer_limit=(positive_int(plan.get("composer_limit")) or None),
        dry_run=dry_run,
    )
