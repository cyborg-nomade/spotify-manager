"""Stable discography result serialization."""

from spotify_manager.interfaces.http.models.discography import DiscographyArtistResult
from spotify_manager.routines import discography


def discography_artist_result(
    selection: discography.ArtistSelection,
) -> DiscographyArtistResult:
    """Convert one planned discography artist into its API representation.

    Args:
        selection: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return DiscographyArtistResult(
        spotify_id=selection.spotify_id,
        artist=selection.name,
        queue=discography.QUEUE_LABELS[selection.source_queue],
        releases=selection.release_count,
        days=selection.days,
        release_names=[release.name for release in selection.releases],
    )
