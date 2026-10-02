"""Coordinate recommendation history, observation, accepted appends and audit."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.found_art_values import FoundArtSummary
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_history import aggregate_track_history
from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


class RecommendationRunEffects(Protocol):
    """Original history, recommendation, destination and accepted-audit boundaries."""

    def refresh(
        self, generated_at: datetime, dry_run: bool
    ) -> tuple[list[Scrobble], int]:
        """Refresh canonical history using the original preview semantics.

        Args:
            generated_at: Resolved UTC timestamp.
            dry_run: Original preview mode.

        Returns:
            Ordered canonical plays and the live-added count.
        """

    def read(self) -> PlaylistState:
        """Observe the destination after history refresh.

        Returns:
            Original size and membership.
        """

    def seeds(
        self, history: tuple[TrackHistory, ...], count: int, week: date
    ) -> tuple[FoundArtSeed, ...]:
        """Select original seeds after destination capacity is known.

        Args:
            history: Aggregated canonical plays.
            count: Original seed count.
            week: Original effective listening week.

        Returns:
            Ordered original seeds.
        """

    def gather(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[TrackKey],
        week: date,
        pool_size: int,
        generated_at: datetime,
    ) -> tuple[FoundArtCandidate, ...]:
        """Observe and checkpoint neighborhoods before catalog resolution.

        Args:
            seeds: Ordered selected seeds.
            heard: Normalized listening exclusions.
            week: Original effective listening week.
            pool_size: Original minimum or scaled candidate limit.
            generated_at: Original effective UTC timestamp.

        Returns:
            Ordered ranked candidates.
        """

    def resolve(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        playlist: PlaylistState,
        count: int,
        dry_run: bool,
    ) -> tuple[tuple[FoundArtResult, ...], tuple[SpotifyTrackMatch, ...]]:
        """Resolve original catalog matches and live liked status.

        Args:
            candidates: Ordered original pool.
            playlist: Original destination membership.
            count: Requested additions.
            dry_run: Original preview mode.

        Returns:
            Ordered outcomes and unique pending additions.
        """

    def append(self, pending: list[SpotifyTrackMatch]) -> None:
        """Accept the original ordered remote additions.

        Args:
            pending: Original matches in selection order.
        """

    def audit(self, summary: FoundArtSummary) -> None:
        """Append the original audit after accepted effects, including previews.

        Args:
            summary: Completed original result.
        """


@dataclass(frozen=True)
class RecommendationBatch:
    """Recommendation observations and ordered selections for one destination run.

    Args:
        seeds: Original selected neighborhood seeds.
        candidates: Original ranked neighborhood pool.
        results: Original ordered candidate outcomes.
        pending: Original ordered unique pending matches.
    """

    seeds: tuple[FoundArtSeed, ...] = ()
    candidates: tuple[FoundArtCandidate, ...] = ()
    results: tuple[FoundArtResult, ...] = ()
    pending: tuple[SpotifyTrackMatch, ...] = ()


def _validate(count: int | None, maximum: int | None, seed_count: int) -> None:
    if count is not None and maximum is not None:
        raise FoundArtConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise FoundArtConfigError("Count must be at least 1.")
    if maximum is not None and maximum < 1:
        raise FoundArtConfigError("Maximum playlist length must be at least 1.")
    if seed_count < 1:
        raise FoundArtConfigError("Seed count must be at least 1.")


def _requested(count: int | None, maximum: int | None, total: int, default: int) -> int:
    if maximum is not None:
        return max(0, maximum - total)
    return count if count is not None else default


@dataclass(frozen=True)
class RecommendationRun:
    """Refresh history before checking capacity and audit after accepted effects.

    Args:
        effects: Existing observation, checkpoint, append and audit boundaries.
        clock: Resolve UTC time after request validation.
        listening_week: Resolve the effective calendar week once per run.
        progress: Present original playlist and append progress.
        default_count: Original default when both count and maximum are absent.
        minimum_pool: Original minimum candidate pool size.
        pool_multiplier: Original count-based candidate pool multiplier.
    """

    effects: RecommendationRunEffects
    clock: Callable[[], datetime]
    listening_week: Callable[[datetime], date]
    progress: Callable[[str], None]
    default_count: int = 20
    minimum_pool: int = 100
    pool_multiplier: int = 10

    def run(
        self,
        playlist_id: str,
        count: int | None,
        maximum: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> FoundArtSummary:
        """Coordinate original preview history, cache and audit effects.

        Args:
            playlist_id: Original summary destination.
            count: Optional explicit addition count.
            maximum: Optional destination capacity.
            seed_count: Original positive seed count.
            dry_run: Suppress remote appends and present proposed additions.

        Returns:
            Original completed summary after its audit is accepted.

        Raises:
            FoundArtConfigError: Request configuration is invalid.
            FoundArtStateError: History, cache, seed selection or audit is unusable.
            SpotifyTrackResolutionError: Catalog or destination data is unusable.
        """
        _validate(count, maximum, seed_count)
        generated_at = self.clock()
        week = self.listening_week(generated_at)
        scrobbles, live_added = self.effects.refresh(generated_at, dry_run)
        history = aggregate_track_history(scrobbles)
        self.progress("Loading the Found Art Spotify playlist")
        playlist = self.effects.read()
        requested = _requested(count, maximum, playlist.total_items, self.default_count)
        batch = self._select(
            history, playlist, requested, seed_count, week, generated_at, dry_run
        )
        added = self._append(batch.pending, dry_run)
        summary = FoundArtSummary(
            generated_at,
            week,
            playlist_id,
            requested,
            len(batch.seeds),
            len(history),
            len(scrobbles),
            live_added,
            len(batch.candidates),
            playlist.total_items,
            playlist.total_items + added,
            dry_run,
            batch.seeds,
            batch.results,
        )
        self.effects.audit(summary)
        return summary

    def _select(
        self,
        history: tuple[TrackHistory, ...],
        playlist: PlaylistState,
        requested: int,
        seed_count: int,
        week: date,
        generated_at: datetime,
        dry_run: bool,
    ) -> RecommendationBatch:
        if not requested:
            return RecommendationBatch()
        seeds = self.effects.seeds(history, seed_count, week)
        heard = {track.key for track in history}
        pool_size = max(self.minimum_pool, requested * self.pool_multiplier)
        candidates = self.effects.gather(seeds, heard, week, pool_size, generated_at)
        results, pending = self.effects.resolve(
            candidates, playlist, requested, dry_run
        )
        return RecommendationBatch(seeds, candidates, results, pending)

    def _append(self, pending: tuple[SpotifyTrackMatch, ...], dry_run: bool) -> int:
        if not pending or dry_run:
            return 0
        self.progress(f"Adding {len(pending)} tracks to Found Art")
        self.effects.append(list(pending))
        return len(pending)
