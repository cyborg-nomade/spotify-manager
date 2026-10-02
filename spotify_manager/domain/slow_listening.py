"""Pure track mapping and date grouping for interactive studio progression."""

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.releases import release_identity
from spotify_manager.domain.releases import studio_date_key


def track_index(tracks: tuple[ReleaseTrack, ...], source: PlaylistTrack) -> int | None:
    """Map a source to its preferred edition by ID, then an unambiguous title.

    Args:
        tracks: Ordered tracks on the selected edition.
        source: Current playlist marker.

    Returns:
        First exact ID match, sole edition-neutral title match, or no match.
    """
    for index, track in enumerate(tracks):
        if track.spotify_id == source.spotify_id:
            return index
    identity = release_identity(source.name)
    matches = []
    for index, track in enumerate(tracks):
        if release_identity(track.name) == identity:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def date_groups(
    discography: tuple[DiscographyRelease, ...],
) -> tuple[tuple[DiscographyRelease, ...], ...]:
    """Group selected editions by their normalized chronology without choosing ties.

    Args:
        discography: Selected editions in existing catalog order.

    Returns:
        Chronological groups retaining the original order within each date.
    """
    groups: dict[tuple[int, int, int, str], list[DiscographyRelease]] = {}
    for release in discography:
        groups.setdefault(studio_date_key(release.chronology_date), []).append(release)
    ordered = []
    for key in sorted(groups):
        ordered.append(tuple(groups[key]))
    return tuple(ordered)
