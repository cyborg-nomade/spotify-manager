"""Small typed catalog facts shared by independent policy and use-case tests."""

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.releases import release_identity


def studio_release(
    identifier: str, name: str, date: str = "2020"
) -> DiscographyRelease:
    """Build one already-parsed eligible edition.

    Args:
        identifier: Spotify identifier.
        name: Display title, whose identity follows the existing edition rule.
        date: Original and chronological release date.

    Returns:
        A plain, unsaved studio album with one track.
    """
    return DiscographyRelease(
        identifier,
        f"spotify:album:{identifier}",
        name,
        "Album",
        date,
        date,
        1,
        "artist",
        "Artist",
        release_identity(name),
        False,
        True,
        0,
    )


def playlist_track(identifier: str, release: DiscographyRelease) -> PlaylistTrack:
    """Build one source marker with its original release facts.

    Args:
        identifier: Marker's Spotify identifier and display title.
        release: Parsed release attached to the marker.

    Returns:
        A complete, playable source marker.
    """
    candidate = ReleaseCandidate(
        release.spotify_id,
        release.uri,
        release.name,
        release.release_type,
        release.release_date,
        release.total_tracks,
        release.primary_artist_id,
        release.primary_artist_name,
    )
    return PlaylistTrack(
        identifier,
        f"spotify:track:{identifier}",
        identifier,
        "artist",
        "Artist",
        candidate,
    )


def release_track(identifier: str) -> ReleaseTrack:
    """Build the first playable track on a selected release.

    Args:
        identifier: Track identifier and display title.

    Returns:
        A track at disc one, position one.
    """
    return ReleaseTrack(identifier, f"spotify:track:{identifier}", identifier, 1, 1)
