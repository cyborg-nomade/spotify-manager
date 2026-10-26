"""Stable discography result serialization."""

from collections.abc import Iterable

from spotify_manager.interfaces.http.models.discography import DiscographyArtistResult
from spotify_manager.interfaces.operations import discography as discography


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


def discography_artist_results(
    values: Iterable[discography.ArtistSelection],
) -> list[DiscographyArtistResult]:
    """Present the complete collection in encounter order.

    Args:
        values: Complete routine values in encounter order.

    Returns:
        Complete response entries, preserving the first conversion failure.
    """
    entries = []
    for value in values:
        entries.append(discography_artist_result(value))
    return entries
