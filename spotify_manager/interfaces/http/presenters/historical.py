"""Stable historical result serialization."""

from spotify_manager.interfaces.http.models.historical import BlastSelectionResult
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past


def blast_selection_result(
    result: blast_from_past.SpotifySelectionResult,
) -> BlastSelectionResult:
    """Convert one routine result into its stable API representation.

    Args:
        result: Accepted routine observation to present.

    Returns:
        The original wire fields, defaults and encounter order.
    """
    selection = result.selection
    scrobble = selection.scrobble
    lastfm_album = scrobble.album or "(no album)"
    spotify_match = None
    liked = None
    track_similarity = None
    album_similarity = None
    if result.match is not None:
        spotify_album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - "
            f"{spotify_album}"
        )
        liked = result.match.liked
        track_similarity = result.match.track_similarity
        album_similarity = result.match.album_similarity
    return BlastSelectionResult(
        selected_date=selection.selected_date.isoformat(),
        page=selection.page,
        total_pages=selection.total_pages,
        direction=selection.direction,
        position=selection.position,
        lastfm_scrobble=f"{scrobble.artist} - {scrobble.track} - {lastfm_album}",
        spotify_match=spotify_match,
        liked=liked,
        track_similarity=track_similarity,
        album_similarity=album_similarity,
        qualifying_matches=result.qualifying_matches,
        action=result.action,
    )
