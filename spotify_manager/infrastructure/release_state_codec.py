"""Decode tolerant legacy release restart documents without changing validation."""

from copy import deepcopy
from typing import Any
from typing import cast

from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


# Constructor keywords remain unvalidated at this legacy JSON boundary.
# The original dataclasses accept arbitrary field values and reject bad shapes.
type ConstructorFields = dict[str, Any]


def default_state(version: int) -> ReleaseState:
    """Create the original empty restart document with its stable key order.

    Args:
        version: Original release-state schema version.

    Returns:
        Original empty state, including additive durability fields.
    """
    return {
        "version": version,
        "updated_at": None,
        "last_successful_check_at": None,
        "last_checked_through": None,
        "artist_mappings": {},
        "skipped_artists": {},
        "processed_releases": {},
        "pending_singles": {},
        "active_run": None,
    }


def validate_state(raw: object, version: int) -> ReleaseState:
    """Copy legacy state, add original defaults and retain unknown fields.

    Args:
        raw: Untrusted decoded restart document.
        version: Original required schema version.

    Returns:
        Original normalized independent state copy.

    Raises:
        ReleaseCheckStateError: Required version or section shapes are invalid.
    """
    if isinstance(raw, dict):
        raw = deepcopy(raw)
        raw.setdefault("updated_at", None)
        raw.setdefault("skipped_artists", {})
    if (
        not isinstance(raw, dict)
        or raw.get("version") != version
        or not isinstance(raw.get("artist_mappings"), dict)
        or not isinstance(raw.get("skipped_artists"), dict)
        or not isinstance(raw.get("processed_releases"), dict)
        or not isinstance(raw.get("pending_singles"), dict)
        or (
            raw.get("active_run") is not None
            and not isinstance(raw["active_run"], dict)
        )
    ):
        raise ReleaseCheckStateError("Release-check state is invalid.")
    return cast(ReleaseState, raw)


def active_artists(active: ReleaseState) -> tuple[RankedArtist, ...]:
    """Restore original dataclass fields without imposing new value validation.

    Args:
        active: Original active-run document.

    Returns:
        Frozen original ranking in stored order.

    Raises:
        ReleaseCheckStateError: The ranking list or a constructor shape is invalid.
    """
    raw_artists = active.get("artists")
    if not isinstance(raw_artists, list):
        raise ReleaseCheckStateError("The active release-check ranking is invalid.")
    try:
        return tuple(
            RankedArtist(**cast(ConstructorFields, raw)) for raw in raw_artists
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseCheckStateError(
            "The active release-check ranking is invalid."
        ) from exc


def mapped_artist(raw: object) -> SpotifyArtistCandidate | None:
    """Decode an original stored mapping, tolerating malformed constructor shapes.

    Args:
        raw: Untrusted stored mapping.

    Returns:
        Original field values or no valid constructor shape.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return SpotifyArtistCandidate(**cast(ConstructorFields, raw))
    except TypeError, ValueError:
        return None


def pending_single(raw: object) -> PendingSingle | None:
    """Decode a retained single using original constructor and string coercion rules.

    Args:
        raw: Untrusted pending-single record.

    Returns:
        Original retained marker or no valid constructor shape.
    """
    if not isinstance(raw, dict):
        return None
    try:
        return PendingSingle(
            artist_key=str(raw["artist_key"]),
            release=ReleaseCandidate(**cast(ConstructorFields, raw["release"])),
            first_track=ReleaseTrack(**cast(ConstructorFields, raw["first_track"])),
        )
    except KeyError, TypeError, ValueError:
        return None
