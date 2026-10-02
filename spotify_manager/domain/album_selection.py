"""Ordered recommendation outcomes and fresh destination exclusions."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Literal

from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.catalog import PlaylistTrack


SauvignonAction = Literal[
    "added",
    "would add",
    "already represented",
    "artist already selected",
    "skipped",
    "quit",
]


@dataclass(frozen=True)
class SauvignonResult:
    """One ranked recommendation and its final playlist action.

    Args:
        recommendation: Original ranked album evidence.
        album: Chosen edition, when selected.
        first_track: Observed playable marker, when loaded.
        action: Original selection or accepted-effect outcome.
    """

    recommendation: AlbumRecommendation
    album: SpotifyAlbumOption | None
    first_track: FirstTrack | None
    action: SauvignonAction


PendingAlbum = tuple[SpotifyAlbumOption, FirstTrack]


def fresh_additions(
    pending: tuple[PendingAlbum, ...], current: tuple[PlaylistTrack, ...]
) -> list[PendingAlbum]:
    """Exclude albums or first tracks already present in the fresh destination.

    Args:
        pending: Original ordered proposals.
        current: Latest destination observation.

    Returns:
        Remaining proposals in original order.
    """
    album_ids = {track.release.spotify_id for track in current}
    track_ids = {track.spotify_id for track in current}
    additions = []
    for album, track in pending:
        if album.spotify_id in album_ids or track.spotify_id in track_ids:
            continue
        additions.append((album, track))
    return additions


def accepted_results(
    results: tuple[SauvignonResult, ...], additions: list[PendingAlbum]
) -> tuple[SauvignonResult, ...]:
    """Project proposals suppressed by fresh membership to their original outcome.

    Args:
        results: Original ordered selection outcomes.
        additions: Accepted remaining proposals.

    Returns:
        Ordered outcomes with only suppressed real additions changed.
    """
    added_ids = {album.spotify_id for album, _track in additions}
    return tuple(_accepted_result(result, added_ids) for result in results)


def _accepted_result(result: SauvignonResult, added_ids: set[str]) -> SauvignonResult:
    if result.action != "added" or result.album is None:
        return result
    if result.album.spotify_id in added_ids:
        return result
    return replace(result, action="already represented")
