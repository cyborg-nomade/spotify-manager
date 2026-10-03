"""Stable wine result serialization."""

from spotify_manager.interfaces.http.models.wine import NewWineCellarTrackResult
from spotify_manager.interfaces.http.models.wine import NewWineRefillResult
from spotify_manager.interfaces.http.models.wine import NewWineTrackResult
from spotify_manager.routines import new_wine


def new_wine_track_result(result: new_wine.FlushResult) -> NewWineTrackResult:
    """Convert one New Wine result into its stable API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    return NewWineTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        release=result.release,
        release_type=result.release_type,
        current_liked=result.current_liked,
        consecutive_unliked=result.consecutive_unliked,
        action=result.action,
        target_track=result.target_track,
        album_unsaved=result.album_unsaved,
        advance_reason=result.advance_reason,
        drop_reason=result.drop_reason,
        continuation_release=result.continuation_release,
        continuation_track=result.continuation_track,
        canonical_track_count=result.canonical_track_count,
        canonical_cutoff_track=result.canonical_cutoff_track,
    )


def new_wine_refill_result(
    refill: new_wine.CellarRefillSummary | None,
) -> NewWineRefillResult | None:
    """Convert a Wine Cellar refill while keeping web payloads compact.

    Args:
        refill: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    if refill is None:
        return None
    return NewWineRefillResult(
        target_size=refill.target_size,
        before=refill.before,
        after=refill.after,
        added=refill.added,
        removed_from_cellar=refill.removed_from_cellar,
        ineligible=refill.ineligible,
        no_discovery=refill.no_discovery,
        results=_cellar_track_results(refill.results),
    )


def _cellar_track_results(
    results: tuple[new_wine.CellarRefillResult, ...],
) -> list[NewWineCellarTrackResult]:
    entries = []
    for result in results:
        if result.action == "ineligible":
            continue
        entry = NewWineCellarTrackResult(
            artist=result.artist,
            source_track=result.source_track,
            action=result.action,
            liked_tracks=result.liked_tracks,
            saved_albums=result.saved_albums,
        )
        entries.append(entry)
    return entries
