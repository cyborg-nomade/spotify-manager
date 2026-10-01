"""Observe recommendation batches before applying ordered selection rules."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_matching import RecommendationSelection


@dataclass(frozen=True)
class RecommendationResolution:
    """Search complete batches before reading liked status and projecting candidates.

    Args:
        search: Existing album-free search boundary.
        liked: Existing complete-batch liked-status boundary.
        progress: Original progress presenter.
        batch_size: Original observation batch size.
        multiplier: Original candidate search limit multiplier.
    """

    search: Callable[[Scrobble], tuple[SpotifyTrackMatch, ...]]
    liked: Callable[[list[tuple[SpotifyTrackMatch, ...]]], set[str]]
    progress: Callable[[str], None]
    batch_size: int = 10
    multiplier: int = 10

    def run(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        playlist: PlaylistState,
        count: int,
        dry_run: bool,
    ) -> tuple[tuple[FoundArtResult, ...], tuple[SpotifyTrackMatch, ...]]:
        """Resolve ranked candidates in original batches until enough additions exist.

        Args:
            candidates: Original ordered ranked pool.
            playlist: Observed membership.
            count: Original requested addition count.
            dry_run: Present selected additions as previews when true.

        Returns:
            Ordered candidate outcomes and ordered unique pending additions.

        Raises:
            SpotifyTrackResolutionError: An observation is unusable.
            ValueError: The configured batch size is zero.
        """
        selection = RecommendationSelection(playlist, count, dry_run)
        maximum = min(len(candidates), max(count, count * self.multiplier))
        for start in range(0, maximum, self.batch_size):
            if len(selection.pending) >= count:
                break
            batch = candidates[start : start + self.batch_size]
            groups = self._search(batch, start, maximum, selection)
            self.progress("Checking candidates against Spotify Liked Songs")
            liked_ids = self.liked(groups)
            self._project(batch, groups, liked_ids, selection)
        return tuple(selection.results), tuple(selection.pending)

    def _search(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        start: int,
        maximum: int,
        selection: RecommendationSelection,
    ) -> list[tuple[SpotifyTrackMatch, ...]]:
        groups: list[tuple[SpotifyTrackMatch, ...]] = []
        for index, candidate in enumerate(candidates, start=start + 1):
            if selection.skips_search(candidate):
                groups.append(())
                continue
            self.progress(f"Searching Spotify candidate {index}/{maximum}")
            play = Scrobble(candidate.track, candidate.artist, "", 0)
            groups.append(self.search(play))
        return groups

    def _project(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        groups: list[tuple[SpotifyTrackMatch, ...]],
        liked_ids: set[str],
        selection: RecommendationSelection,
    ) -> None:
        for candidate, matches in zip(candidates, groups, strict=True):
            if not selection.observe(candidate, matches, liked_ids):
                break
