"""Resolve historical plays with ordered searches and one shared liked observation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from spotify_manager.application.historical_values import SpotifySelectionResolution
from spotify_manager.application.historical_values import SpotifySelectionResult
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import ScrobbleSelection
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import preferred_match
from spotify_manager.domain.history_matching import qualifying_matches


type MatchAction = Literal[
    "added", "already present", "duplicate selection", "no match"
]


def _action(
    match: SpotifyTrackMatch | None,
    playlist: PlaylistState,
    pending: list[SpotifyTrackMatch],
    pending_ids: set[str],
) -> MatchAction:
    if match is None:
        return "no match"
    if match.spotify_id in playlist.track_ids:
        return "already present"
    if match.spotify_id in pending_ids:
        return "duplicate selection"
    pending_ids.add(match.spotify_id)
    pending.append(match)
    return "added"


def _project(
    selections: tuple[ScrobbleSelection, ...],
    groups: list[tuple[SpotifyTrackMatch, ...]],
    liked: set[str],
    playlist: PlaylistState,
    threshold: float,
) -> SpotifySelectionResolution:
    pending: list[SpotifyTrackMatch] = []
    pending_ids: set[str] = set()
    results = []
    for selection, matches in zip(selections, groups, strict=True):
        qualified = qualifying_matches(matches, liked, threshold)
        match = preferred_match(matches, liked, threshold)
        action = _action(match, playlist, pending, pending_ids)
        results.append(SpotifySelectionResult(selection, match, len(qualified), action))
    return SpotifySelectionResolution(tuple(results), tuple(pending))


@dataclass(frozen=True)
class HistoricalResolution:
    """Observe every search before liked status and preserve selection-order decisions.

    Args:
        search: Search one selected play using the existing adapter semantics.
        liked: Read liked status for all ordered match groups.
        check_cancel: Existing per-selection cancellation boundary.
        progress: Existing progress presenter.
        album_threshold: Existing overridable album qualification threshold.
    """

    search: Callable[[Scrobble], tuple[SpotifyTrackMatch, ...]]
    liked: Callable[[list[tuple[SpotifyTrackMatch, ...]]], set[str]]
    check_cancel: Callable[[], None]
    progress: Callable[[str], None]
    album_threshold: float = 0.9

    def run(
        self, selections: tuple[ScrobbleSelection, ...], playlist: PlaylistState
    ) -> SpotifySelectionResolution:
        """Resolve all plays before projecting existing membership and duplicates.

        Args:
            selections: Original ordered selected plays.
            playlist: Observed destination membership.

        Returns:
            Ordered per-selection outcomes and the pending unique matches.

        Raises:
            BlastFromPastCancelledError: Cancellation is requested.
            SpotifyTrackResolutionError: An observation returns unusable data.
        """
        groups = []
        for index, selection in enumerate(selections, start=1):
            self.check_cancel()
            self.progress(f"Searching Spotify track {index}/{len(selections)}")
            groups.append(self.search(selection.scrobble))
        self.progress("Checking liked Spotify matches")
        liked = self.liked(groups)
        return _project(selections, groups, liked, playlist, self.album_threshold)


def direct_call(operation: Callable[[], object], _description: str) -> object:
    """Execute the original direct observation when no outer retry is supplied.

    Args:
        operation: Original delayed observation.
        _description: Original passive callback description.

    Returns:
        Original observation result, propagating its original failure unchanged.
    """
    return operation()
