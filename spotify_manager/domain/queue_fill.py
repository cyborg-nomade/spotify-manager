"""Pure Queue fill sizing and first-unliked-marker policies."""

from spotify_manager.domain.discovery import CatalogTrack


def requested_additions(
    count: int | None,
    maximum: int | None,
    before: int,
    default_count: int = 20,
) -> int:
    """Retain the original count default and capacity calculation.

    Args:
        count: Original optional requested additions.
        maximum: Original optional maximum length.
        before: Original observed Queue length.
        default_count: Original configured default additions.

    Returns:
        Original requested count, or nonnegative remaining capacity.
    """
    if maximum is not None:
        return max(0, maximum - before)
    return count if count is not None else default_count


def first_unliked(
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
) -> CatalogTrack | None:
    """Choose the first unliked marker in an already bounded top-track window.

    Args:
        tracks: Original top tracks in source order.
        liked: Original liked membership, with missing identities unliked.

    Returns:
        Original first unliked marker, or no marker.
    """
    for track in tracks:
        if not liked.get(track.spotify_id, False):
            return track
    return None
