"""Coordinate saved review entries through composer and ordinary release planning."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from typing import Protocol
from typing import cast

from spotify_manager.application.composer_progression import composer_plan
from spotify_manager.application.composer_progression import composer_step
from spotify_manager.application.composer_routes import resolve_composer_route
from spotify_manager.application.discovery_completion import ReviewArtist
from spotify_manager.application.new_kids_execution import NewKidsExecution
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.new_kids_planner import ReviewSource
from spotify_manager.application.new_kids_state import artist_progress
from spotify_manager.application.new_kids_state import source_from_record
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.discovery import DiscoveryAudit
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.composers import is_composer_playlist_candidate
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_progression import catalog_track_index
from spotify_manager.domain.discovery_progression import composer_release
from spotify_manager.domain.progression import primary_artist_tracks


type ProgressCallback = Callable[[int, int, str], None]
type ReviewControl = Literal["skip", "pause"]


class DiscoveryReviewPresentation(Protocol):
    """Render invalidated and skipped composer plans at original boundaries."""

    def stale_plan(self, artist: str) -> None:
        """Show stale composer-plan removal before its checkpoint.

        Args:
            artist: Logical artist display name.
        """

    def skipped(self, artist: str) -> None:
        """Show a composer skip after its checkpoint.

        Args:
            artist: Logical artist display name.
        """


@dataclass(frozen=True)
class ReviewEntry:
    """Decoded source and mutable records for one snapshotted review entry.

    Args:
        source: Original source marker.
        artist: Logical artist credit.
        record: Mutable durable run entry.
        progress: Mutable artist progress within the namespace.
    """

    source: PlaylistTrack
    artist: ReviewArtist
    record: dict[str, object]
    progress: dict[str, object]


def _current_release(
    source: PlaylistTrack, artist: ReviewArtist, catalog: tuple[RankedRelease, ...]
) -> RankedRelease:
    fallback = composer_release(source, artist.identifier, artist.name)
    for release in catalog:
        if release.spotify_id == source.release.spotify_id:
            return release
    return fallback


@dataclass(frozen=True)
class DiscoveryReview:
    """Own review decisions, skip/pause boundaries and completion audit order.

    Args:
        planner: Ordinary release planner and shared observations.
        execution: Accepted plan executor and mutable run state.
        state_access: Original namespace checkpoint boundary.
        audit: Original routine event sink.
        presentation: Original stale/skip messages.
        owned: Observed owned playlists for composer matching.
        excluded: Review playlists excluded from composer routing.
        clock: Original UTC clock for progress and accepted routes.
        composer_limit: Original maximum reviewed works.
        progress_callback: Optional original progress sink.
    """

    planner: NewKidsPlanner
    execution: NewKidsExecution
    state_access: RoutineState
    audit: DiscoveryAudit
    presentation: DiscoveryReviewPresentation
    owned: tuple[OwnedPlaylist, ...]
    excluded: frozenset[str]
    clock: Callable[[], datetime]
    composer_limit: int = 40
    progress_callback: ProgressCallback | None = None

    def review(
        self, entries: list[object], run_id: object
    ) -> tuple[tuple[FlushResult, ...], bool]:
        """Review pending entries in snapshot order until completion or operator pause.

        Args:
            entries: Previously validated original run entry sequence.
            run_id: Original audit identifier, retaining tolerant missing values.

        Returns:
            Public results and whether an operator choice paused the review.

        Raises:
            NewKidsStateError: An entry, source or composer route is malformed.
            NewKidsError: Planning or execution rejects unavailable catalog facts.
        """
        results: list[FlushResult] = []
        for index, raw in enumerate(entries, start=1):
            outcome = self._entry(raw, index, len(entries), run_id)
            if outcome == "pause":
                return tuple(results), True
            if isinstance(outcome, FlushResult):
                results.append(outcome)
        return tuple(results), False

    def _entry(
        self, raw: object, index: int, total: int, run_id: object
    ) -> FlushResult | ReviewControl:
        if not isinstance(raw, dict):
            raise NewKidsStateError("New Kids run contains an invalid entry.")
        if raw.get("status") in {"completed", "skipped"}:
            return "skip"
        entry = self._entry_context(raw, index, total)
        plan = self._prepared_plan(entry)
        if isinstance(plan, str):
            return plan
        context = self._context(entry)
        if plan is None:
            decision = self.planner.plan(context)
            if decision is None:
                return "pause"
            if isinstance(decision, FlushResult):
                return self._skipped(entry, decision)
            plan = decision
            self._accept(entry, plan)
        result = self.execution.execute(
            entry.source, entry.artist, entry.record, entry.progress, plan
        )
        self.audit.event("track_completed", run_id=run_id, result=asdict(result))
        self._progress(index, total, f"Completed {entry.artist.name}")
        return result

    def _entry_context(
        self, raw: dict[str, object], index: int, total: int
    ) -> ReviewEntry:
        source = source_from_record(raw.get("source"))
        artist = ReviewArtist(
            str(raw.get("artist_id") or source.primary_artist_id),
            str(raw.get("artist_name") or source.primary_artist_name),
        )
        self._progress(index - 1, total, f"{artist.name} - {source.name}")
        progress = artist_progress(
            self.execution.state, source, artist.identifier, artist.name, self.clock
        )
        return ReviewEntry(source, artist, raw, progress)

    def _prepared_plan(
        self, entry: ReviewEntry
    ) -> dict[str, object] | ReviewControl | None:
        raw = entry.record.get("plan")
        plan = cast(dict[str, object], raw) if isinstance(raw, dict) else None
        if plan is not None and plan.get("composer_playlist_id"):
            if not self._valid_composer(
                entry.artist.name, str(plan["composer_playlist_id"])
            ):
                plan = None
                self._discard(entry)
        if plan is not None:
            return plan
        return self._composer(entry)

    def _valid_composer(self, artist: str, playlist: str) -> bool:
        return is_composer_playlist_candidate(
            artist, playlist, self.owned, excluded_playlist_ids=self.excluded
        )

    def _discard(self, entry: ReviewEntry) -> None:
        entry.record["plan"] = None
        routes = self.execution.state.get("composer_routes")
        if isinstance(routes, dict):
            routes.pop(entry.artist.identifier, None)
        self.presentation.stale_plan(entry.artist.name)
        self._checkpoint()

    def _composer(self, entry: ReviewEntry) -> dict[str, object] | ReviewControl | None:
        playlist, choice = resolve_composer_route(
            self.execution.state,
            entry.artist.identifier,
            entry.artist.name,
            entry.source.spotify_id,
            self.owned,
            self.excluded,
            self.planner.choose,
            self.clock,
        )
        if choice == "__quit__":
            return "pause"
        if choice == "__skip__":
            entry.record["status"] = "skipped"
            self._checkpoint()
            self.presentation.skipped(entry.artist.name)
            return "skip"
        if playlist is None:
            return None
        plan = self._composer_plan(entry, playlist)
        self._accept(entry, plan)
        return plan

    def _composer_plan(
        self, entry: ReviewEntry, playlist: OwnedPlaylist
    ) -> dict[str, object]:
        observations = self.planner.observations
        tracks = observations.composer_tracks(playlist.spotify_id)
        observations.memberships([entry.source.spotify_id])
        _completed, target = composer_step(entry.source, tracks, self.composer_limit)
        assessment = None
        if target is None:
            catalog = observations.catalog(entry.artist.identifier)
            assessment = observations.assessment(entry.artist.identifier, catalog)
        return composer_plan(
            entry.source,
            entry.artist.identifier,
            entry.artist.name,
            playlist,
            tracks,
            current_liked=observations.liked[entry.source.spotify_id],
            assessment=assessment,
            limit=self.composer_limit,
        )

    def _context(self, entry: ReviewEntry) -> ReviewSource:
        observations = self.planner.observations
        catalog = observations.catalog(entry.artist.identifier)
        release = _current_release(entry.source, entry.artist, catalog)
        if all(candidate.identity != release.identity for candidate in catalog):
            catalog = (release, *catalog)
        tracks = observations.tracks(release)
        primary = primary_artist_tracks(tracks, entry.artist.identifier)
        return ReviewSource(
            entry.source,
            entry.artist.identifier,
            entry.artist.name,
            entry.progress,
            catalog,
            release,
            tracks,
            primary,
            catalog_track_index(primary, entry.source),
        )

    def _skipped(self, entry: ReviewEntry, result: FlushResult) -> FlushResult:
        entry.record["status"] = "skipped"
        self.audit.event(
            "artist_skipped_run",
            artist=entry.artist.name,
            artist_id=entry.artist.identifier,
            dry_run=self.execution.dry_run,
        )
        self._checkpoint()
        return result

    def _accept(self, entry: ReviewEntry, plan: dict[str, object]) -> None:
        entry.record["plan"] = plan
        self._checkpoint()

    def _checkpoint(self) -> None:
        if not self.execution.dry_run:
            self.state_access.save(self.execution.state)

    def _progress(self, done: int, total: int, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(done, total, message)
