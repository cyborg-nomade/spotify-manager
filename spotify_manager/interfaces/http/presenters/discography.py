"""Stable discography result serialization."""

from collections.abc import Iterable

from spotify_manager.application.ports.discography_review import ReleaseReviewDraft
from spotify_manager.interfaces.http.models.discography import DiscographyArtistResult
from spotify_manager.interfaces.http.models.discography import DiscographyReleaseOption
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
        release_ids=[release.spotify_id for release in selection.releases],
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


def discography_review_options(
    draft: ReleaseReviewDraft,
) -> list[DiscographyReleaseOption]:
    """Present exact fetched and linked editions without losing credits.

    Args:
        draft: Current editable artist checklist.

    Returns:
        Complete chronological options with explicit-addition metadata.
    """
    result = []
    for entry in draft.entries:
        release = entry.release
        result.append(
            DiscographyReleaseOption(
                spotify_id=release.spotify_id,
                name=release.name,
                release_type=release.release_type,
                release_date=release.chronology_date,
                total_tracks=release.total_tracks,
                saved=release.saved,
                default=release.default,
                artists=list(entry.artists),
                linked=entry.linked,
            )
        )
    return result
