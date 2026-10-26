"""Refresh Sauvignon evidence, select editions, recheck membership and audit."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.ports.calendar import ListeningCalendar
from spotify_manager.application.ports.runtime import Clock
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.application.sauvignon_selection import AlbumEditionChoice
from spotify_manager.application.sauvignon_selection import AlbumSelection
from spotify_manager.application.sauvignon_values import SauvignonConfigError
from spotify_manager.application.sauvignon_values import SauvignonSummary
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_recommendations import canonical_album_key
from spotify_manager.domain.album_recommendations import heard_album_keys
from spotify_manager.domain.album_selection import PendingAlbum
from spotify_manager.domain.album_selection import accepted_results
from spotify_manager.domain.album_selection import fresh_additions
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import aggregate_track_history
from spotify_manager.domain.recommendation_history import listening_week_start
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


@dataclass(frozen=True)
class SauvignonStages:
    """Name the application stages of one album discovery run.

    Args:
        seeds: Weighted history seed selection.
        candidates: Last.fm neighborhood gathering and ranking.
        albums: Album evidence gathering and ranking.
        choice: Edition policy and optional operator interaction.
    """

    seeds: RecommendationSeeds
    candidates: CandidateGathering
    albums: AlbumGathering
    choice: AlbumEditionChoice


class SauvignonEffects(Protocol):
    """Caller-owned history, catalog, interaction and durable effect boundaries."""

    def prepare(self) -> None:
        """Resolve the invocation's retry policy after validating its options."""
        ...

    def refresh(
        self, generated_at: datetime, dry_run: bool
    ) -> tuple[list[Scrobble], int]:
        """Refresh canonical history.

        Args:
            generated_at: Effective UTC time.
            dry_run: Original preview semantics.

        Returns:
            Plays and live-added count.
        """

    def read(self) -> tuple[PlaylistTrack, ...]:
        """Observe original ordered destination membership.

        Returns:
            Playable markers.
        """

    def previous(self) -> set[AlbumKey]:
        """Read prior accepted additions.

        Returns:
            Normalized album exclusions.
        """

    def first(self, album: SpotifyAlbumOption) -> FirstTrack:
        """Read a playable marker before any playlist mutation.

        Args:
            album: Selected edition.

        Returns:
            First playable track.
        """

    def append(self, additions: list[PendingAlbum]) -> None:
        """Accept the original ordered append.

        Args:
            additions: Freshly filtered proposals.
        """

    def audit(self, summary: SauvignonSummary) -> None:
        """Append the original result after all accepted effects.

        Args:
            summary: Original completed outcome.
        """


def _validate(count: int | None, maximum: int | None, seeds: int) -> None:
    if count is not None and maximum is not None:
        raise SauvignonConfigError(
            "Use either count or maximum playlist length, not both."
        )
    if count is not None and count < 1:
        raise SauvignonConfigError("Count must be at least 1.")
    if maximum is not None and maximum < 1:
        raise SauvignonConfigError("Maximum playlist length must be at least 1.")
    if seeds < 1:
        raise SauvignonConfigError("Seed count must be at least 1.")


@dataclass(frozen=True)
class AlbumBatch:
    """Observations and selections made after original capacity is known.

    Args:
        seeds: Original selected seeds.
        tracks: Original ranked track candidates.
        albums: Original ranked album candidates.
        selection: Ordered choices and proposals.
    """

    seeds: tuple[FoundArtSeed, ...]
    tracks: tuple[FoundArtCandidate, ...]
    albums: tuple[AlbumRecommendation, ...]
    selection: AlbumSelection


@dataclass(frozen=True)
class SauvignonRun:
    """Preserve sequential recommendation effects and audit acceptance.

    Args:
        effects: Original observations and effects.
        stages: Concrete named application stages for the invocation.
        clock: Original UTC clock, evaluated after validation.
        calendar: Original calendar boundary.
        progress: Original stage presentation.
        output: Original accepted-append presentation.
        default_maximum: Original capacity fallback.
        minimum_pool: Original track pool minimum.
        pool_multiplier: Original track pool scaling.
        minimum_searches: Original album search minimum.
        search_multiplier: Original album search scaling.
    """

    effects: SauvignonEffects
    stages: SauvignonStages
    clock: Clock
    calendar: ListeningCalendar
    progress: Messages
    output: Messages
    default_maximum: int = 20
    minimum_pool: int = 100
    pool_multiplier: int = 10
    minimum_searches: int = 50
    search_multiplier: int = 5

    def run(
        self,
        playlist_id: str,
        count: int | None,
        maximum: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> SauvignonSummary:
        """Refresh history before capacity and audit after accepted additions.

        Args:
            playlist_id: Original destination identity.
            count: Optional explicit addition count.
            maximum: Optional playlist capacity.
            seed_count: Positive requested seed count.
            dry_run: Suppress remote writes, retaining preview audit/cache effects.

        Returns:
            Original result after the audit succeeds.

        Raises:
            SauvignonConfigError: Original request validation fails.
            SauvignonStateError: Durable observations or audit fail.
            SauvignonSpotifyError: Original catalog or destination is unusable.
        """
        _validate(count, maximum, seed_count)
        self.effects.prepare()
        stamp = self.clock.now()
        week = listening_week_start(self.calendar.local_date(stamp))
        history, live_added = self.effects.refresh(stamp, dry_run)
        self.progress.echo("Loading Sauvignon Terre-Neuve")
        playlist = self.effects.read()
        before = len(playlist)
        requested = (
            count
            if count is not None
            else max(0, (maximum or self.default_maximum) - before)
        )
        keys = heard_album_keys(history)
        batch = self._gather(
            history, keys, playlist, requested, seed_count, week, stamp, dry_run
        )
        added = self._append(batch.selection, dry_run)
        summary = SauvignonSummary(
            stamp,
            week,
            playlist_id,
            requested,
            len(keys),
            len(history),
            live_added,
            len(batch.seeds),
            len(batch.tracks),
            len(batch.albums),
            before,
            before + added,
            batch.selection.paused,
            dry_run,
            tuple(batch.selection.results),
        )
        self.effects.audit(summary)
        return summary

    def _gather(
        self,
        history: list[Scrobble],
        keys: set[AlbumKey],
        playlist: tuple[PlaylistTrack, ...],
        requested: int,
        seed_count: int,
        week: date,
        stamp: datetime,
        dry_run: bool,
    ) -> AlbumBatch:
        selection = AlbumSelection(self.stages.choice, self.effects, dry_run)
        if not requested:
            return AlbumBatch((), (), (), selection)
        aggregated = aggregate_track_history(history)
        seeds = self.stages.seeds.run(aggregated, seed_count, week)
        pool = max(self.minimum_pool, requested * self.pool_multiplier)
        tracks = self.stages.candidates.run(
            seeds, {track.key for track in aggregated}, week, pool, stamp
        )
        existing_ids = {track.release.spotify_id for track in playlist}
        existing_keys = set()
        for track in playlist:
            existing_keys.add(
                canonical_album_key(track.primary_artist_name, track.release.name)
            )
        excluded = keys | existing_keys | self.effects.previous()
        maximum = min(
            len(tracks), max(self.minimum_searches, requested * self.search_multiplier)
        )
        albums = self.stages.albums.run(tracks, excluded, existing_ids, maximum, week)
        selection.run(albums, requested)
        return AlbumBatch(seeds, tracks, albums, selection)

    def _append(self, selection: AlbumSelection, dry_run: bool) -> int:
        if not selection.pending or dry_run:
            return 0
        self.progress.echo("Rechecking Sauvignon before adding albums")
        additions = fresh_additions(tuple(selection.pending), self.effects.read())
        if additions:
            self.effects.append(additions)
            self.output.echo(f"Added {len(additions)} albums to Sauvignon Terre-Neuve.")
        selection.results = list(accepted_results(tuple(selection.results), additions))
        return len(additions)
