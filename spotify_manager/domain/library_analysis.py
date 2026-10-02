"""Exact pre/post identity differences and library analysis counts."""

from collections.abc import Sequence

from spotify_manager.domain.library_analysis_values import AnalysisCounts
from spotify_manager.domain.library_analysis_values import LibraryIdentity
from spotify_manager.domain.library_analysis_values import ResourceCounts
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary


def _resource_counts(
    previous: Sequence[LibraryIdentity], current: Sequence[LibraryIdentity]
) -> ResourceCounts:
    added, removed = model_diff(previous, current)
    growth = ((len(current) - len(previous)) / (len(previous) or 1)) * 100
    return ResourceCounts(len(current), len(removed), len(added), growth)


def deduplicate_models[T: LibraryIdentity](models: Sequence[T]) -> list[T]:
    """Deduplicate models by Spotify id while preserving the newest value.

    Args:
        models: Original complete boundary models in encounter order.

    Returns:
        Original latest values in first-identity encounter order.
    """
    by_id: dict[str, T] = {}
    for model in models:
        spotify_id = getattr(model, "spotify_id", "")
        if spotify_id:
            by_id[spotify_id] = model
    return list(by_id.values())


def model_diff[T: LibraryIdentity](
    previous: Sequence[T],
    current: Sequence[T],
) -> tuple[list[T], list[T]]:
    """Return models added to and removed from a Spotify-id keyed mirror.

    Args:
        previous: Original complete models before analysis.
        current: Original complete models after analysis.


    Returns:
        Original added and removed newest-value models in encounter order.
    """
    previous_by_id = {item.spotify_id: item for item in previous}
    current_by_id = {item.spotify_id: item for item in current}
    added = [item for key, item in current_by_id.items() if key not in previous_by_id]
    removed = [item for key, item in previous_by_id.items() if key not in current_by_id]
    return added, removed


def stats_report_for_analysis(
    previous_albums: Sequence[LibraryIdentity],
    albums: Sequence[LibraryIdentity],
    previous_tracks: Sequence[LibraryIdentity],
    tracks: Sequence[LibraryIdentity],
    previous_artists: Sequence[LibraryIdentity],
    artists: Sequence[LibraryIdentity],
) -> AnalysisCounts:
    """Build a stats report from exact pre/post analysis mirrors.

    Args:
        previous_albums: Original pre-analysis saved albums.
        albums: Original complete saved-album facts.
        previous_tracks: Original pre-analysis liked tracks.
        tracks: Original complete liked-track facts.
        previous_artists: Original pre-analysis followed artists.
        artists: Original complete followed-artist facts.


    Returns:
        Original size, membership-difference and growth counts.
    """
    album_counts = _resource_counts(previous_albums, albums)
    track_counts = _resource_counts(previous_tracks, tracks)
    artist_counts = _resource_counts(previous_artists, artists)
    artist_count = max(1, len(artists))
    return AnalysisCounts(
        album_counts,
        track_counts,
        artist_counts,
        len(albums) // artist_count,
        len(tracks) // artist_count,
    )


def resource_summary(
    resource: ResourceName,
    source: str,
    previous: Sequence[LibraryIdentity],
    current: Sequence[LibraryIdentity],
    skipped: int,
) -> ResourceSyncSummary:
    """Build one resource summary and exact diff counts.

    Args:
        resource: Original active library resource identity.
        source: Original source authority or publication label.
        previous: Original complete models before analysis.
        current: Original complete models after analysis.
        skipped: Original skipped raw-row count.


    Returns:
        Original source and exact pre/post difference counts.
    """
    added, removed = model_diff(previous, current)
    return ResourceSyncSummary(
        resource=resource,
        source=source,
        previous=len(previous),
        current=len(current),
        added=len(added),
        removed=len(removed),
        skipped=skipped,
    )


def retry_delay(base: int, maximum: int, attempt: int) -> int:
    """Return the capped exponential delay for a one-based attempt.

    Args:
        base: Original first transient retry delay.
        maximum: Original maximum transient retry delay.
        attempt: Original one-based transient attempt.


    Returns:
        Original capped exponential delay, including zero-wait semantics.
    """
    if base <= 0 or maximum <= 0:
        return 0
    exponent = min(max(0, attempt - 1), maximum.bit_length())
    return min(maximum, base * (1 << exponent))


def verification_candidates[T: LibraryIdentity](
    existing: list[T],
    export: list[T],
    partial_live: list[T],
    full: bool,
) -> tuple[list[T], list[T]]:
    """Select original candidate priority and incremental retained identities.

    Args:
        existing: Original stored followed artists.
        export: Original latest optional export artists.
        partial_live: Original already accepted cursor rows.
        full: Whether every known candidate must be verified live.

    Returns:
        Original verification candidates and immediately retained artists.
    """
    all_candidates = deduplicate_models([*existing, *export, *partial_live])
    if full:
        return all_candidates, []
    retained = deduplicate_models([*existing, *partial_live])
    retained_ids = {item.spotify_id for item in retained}
    candidates: list[T] = []
    for item in all_candidates:
        if item.spotify_id not in retained_ids:
            candidates.append(item)
    return candidates, retained
