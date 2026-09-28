"""Queue 3 source and library representations retain original chronological facts."""

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.releases import release_identity


def source_release(source: PlaylistTrack) -> DiscographyRelease:
    """Represent an ineligible marker for a chronological boundary prompt.

    Args:
        source: Original marker with track-level primary artist credits.

    Returns:
        Unsaved, plain source release retaining original dates and track credits.
    """
    release = source.release
    return DiscographyRelease(
        release.spotify_id,
        release.uri,
        release.name,
        release.release_type,
        release.release_date,
        release.release_date,
        release.total_tracks,
        source.primary_artist_id,
        source.primary_artist_name,
        release_identity(release.name),
        False,
        True,
        0,
    )


def ranked_release(release: DiscographyRelease) -> RankedRelease:
    """Adapt a selected chronological release for shared library reconciliation.

    Args:
        release: Preferred studio edition, including observed saved status.

    Returns:
        Original tier-zero library value without discovery ranking observations.
    """
    return RankedRelease(
        release.spotify_id,
        release.uri,
        release.name,
        release.release_type,
        release.release_date,
        release.total_tracks,
        release.primary_artist_id,
        release.primary_artist_name,
        None,
        None,
        0,
        release.identity,
        release.saved,
        release.plain,
    )
