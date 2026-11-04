"""Resolve historical plays through automatic matching and explicit fallback choices."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Literal

from spotify_manager.application.historical_values import SpotifySelectionResolution
from spotify_manager.application.historical_values import SpotifySelectionResult
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.application.ports.history import HistoricalMatchCatalog
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.runtime import Messages
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
    resolved: list[SpotifyTrackMatch | None],
) -> SpotifySelectionResolution:
    pending: list[SpotifyTrackMatch] = []
    pending_ids: set[str] = set()
    results = []
    for selection, matches, match in zip(selections, groups, resolved, strict=True):
        qualified = qualifying_matches(matches, liked, threshold)
        action = _action(match, playlist, pending, pending_ids)
        results.append(SpotifySelectionResult(selection, match, len(qualified), action))
    return SpotifySelectionResolution(tuple(results), tuple(pending))


@dataclass(frozen=True)
class HistoricalResolution:
    """Observe every search before liked status and preserve selection-order decisions.

    Args:
        catalog: Original search and liked-membership integration.
        check_cancel: Existing per-selection cancellation boundary.
        progress: Existing progress presenter.
        manual: Optional explicit fallback for interactive feature invocations.
    """

    catalog: HistoricalMatchCatalog
    check_cancel: Cancellation
    progress: Messages
    manual: ManualTrackMatching | None = None

    async def run(
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
        threshold = self.catalog.album_threshold
        groups = []
        for index, selection in enumerate(selections, start=1):
            self.check_cancel.check()
            self.progress.echo(f"Searching Spotify track {index}/{len(selections)}")
            groups.append(await self.catalog.search(selection.scrobble))
        self.progress.echo("Checking liked Spotify matches")
        liked = await self.catalog.liked(groups)
        resolved = await self._resolve(selections, groups, liked, threshold)
        return _project(selections, groups, liked, playlist, threshold, resolved)

    async def _resolve(
        self,
        selections: tuple[ScrobbleSelection, ...],
        groups: list[tuple[SpotifyTrackMatch, ...]],
        liked: set[str],
        threshold: float,
    ) -> list[SpotifyTrackMatch | None]:
        resolved = []
        for selection, matches in zip(selections, groups, strict=True):
            match = preferred_match(matches, liked, threshold)
            if match is None and self.manual is not None:
                match = await self._manual_match(selection)
            resolved.append(match)
        return resolved

    async def _manual_match(
        self, selection: ScrobbleSelection
    ) -> SpotifyTrackMatch | None:
        assert self.manual is not None
        match = await self.manual.run(selection.scrobble)
        if match is None:
            return None
        liked = await self.catalog.liked([(match,)])
        return replace(match, liked=match.spotify_id in liked)
