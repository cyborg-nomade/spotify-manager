"""Pure marker mapping and progression within a selected New Wine release."""

from collections.abc import Mapping
from typing import Literal

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack


type SelectedAction = Literal["advance", "sauvignon", "complete single"]


def starts_new_record(source: PlaylistTrack, plan: Mapping[str, object]) -> bool:
    """Identify transitions whose New Wine marker begins another record.

    Args:
        source: Original playlist marker.
        plan: Accepted durable transition fields.

    Returns:
        Whether a follow-up or a different selected release starts a record.
    """
    if plan.get("continuation_target") is not None:
        return True
    release = plan.get("release")
    if plan.get("action") != "advance" or not isinstance(release, dict):
        return False
    return release.get("spotify_id") != source.release.spotify_id


def track_index(tracks: tuple[ReleaseTrack, ...], source: PlaylistTrack) -> int | None:
    """Map a marker by exact ID, then a unique stripped case-insensitive title.

    Args:
        tracks: Ordered selected-release tracks.
        source: Original playlist marker.

    Returns:
        First matching ID or the only matching title index; otherwise None.
    """
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    name = source.name.strip().casefold()
    matches = []
    for index, track in enumerate(tracks):
        if track.name.strip().casefold() == name:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def selected_transition(
    source: PlaylistTrack, release: ReleaseCandidate, tracks: tuple[ReleaseTrack, ...]
) -> tuple[SelectedAction, ReleaseTrack | None]:
    """Choose the next marker or the selected release's completion action.

    Args:
        source: Original playlist marker.
        release: Accepted release, possibly different from the source release.
        tracks: Nonempty ordered tracks within the active canonical endpoint.

    Returns:
        Original action and target, retaining first-track album completion routing.

    Raises:
        IndexError: The caller supplies an empty selected release.
    """
    index = track_index(tracks, source)
    if release.spotify_id != source.release.spotify_id or index is None:
        return "advance", tracks[0]
    if index + 1 < len(tracks):
        return "advance", tracks[index + 1]
    if release.release_type in {"Album", "EP"}:
        return "sauvignon", tracks[0]
    return "complete single", None
