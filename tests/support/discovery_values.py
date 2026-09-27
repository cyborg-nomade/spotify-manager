"""Small parsed discovery catalog values for independent policy tests."""

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease


def release(identifier: str) -> RankedRelease:
    """Build a plain studio album.

    Args:
        identifier: Original ID, title and edition-neutral identity.

    Returns:
        An unsaved studio release with a known date.
    """
    return RankedRelease(
        identifier,
        f"spotify:album:{identifier}",
        identifier,
        "Album",
        "2020",
        2,
        "artist",
        "Artist",
        50,
        1,
        0,
        identifier,
        False,
        True,
    )


def track(identifier: str) -> CatalogTrack:
    """Build one primary-artist catalog track.

    Args:
        identifier: Original ID and title.

    Returns:
        First track of the first disc with no observed popularity.
    """
    return CatalogTrack(
        identifier, f"spotify:track:{identifier}", identifier, 1, 1, "artist", "Artist"
    )
