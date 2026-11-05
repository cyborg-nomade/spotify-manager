"""Identify an existing plan position without restarting its current track."""

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery_history import scrobble_track_identity
from spotify_manager.domain.new_kids_plans import ReleasePlan


def migration_position(plan: ReleasePlan, current_id: str) -> ReleasePlan:
    """Require the current edition and acknowledge all preceding entries.

    Args:
        plan: Operator-selected release order.
        current_id: Confirmed current edition.

    Returns:
        The same releases with the current zero-based position.

    Raises:
        ValueError: The selected order omits the current release.
    """
    for position, release in enumerate(plan.releases):
        if release.spotify_id == current_id:
            return ReleasePlan(plan.releases, position)
    raise ValueError("The plan must include the current album.")


def current_track_matches(
    tracks: tuple[CatalogTrack, ...], identity: str, name: str, confirmed: bool
) -> bool:
    """Accept exact membership or an explicitly resolved unique title match.

    Args:
        tracks: Current edition's primary-artist tracks.
        identity: Existing playlist marker ID.
        name: Existing playlist track title.
        confirmed: Explicit current-edition resolution by the operator.

    Returns:
        Whether the current marker can safely resume in this edition.
    """
    return current_track_index(tracks, identity, name, confirmed) is not None


def current_track_index(
    tracks: tuple[CatalogTrack, ...], identity: str, name: str, confirmed: bool
) -> int | None:
    """Use the same unique mapping during selection and subsequent review.

    Args:
        tracks: Current edition's ordered primary-artist tracks.
        identity: Existing playlist marker ID.
        name: Existing playlist track title.
        confirmed: Whether explicit current-edition resolution was accepted.

    Returns:
        Exact or uniquely confirmed normalized position, otherwise None.
    """
    for index, track in enumerate(tracks):
        if track.spotify_id == identity:
            return index
    if not confirmed:
        return None
    normalized = scrobble_track_identity(name)
    matches = []
    for index, track in enumerate(tracks):
        if normalized and scrobble_track_identity(track.name) == normalized:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None
