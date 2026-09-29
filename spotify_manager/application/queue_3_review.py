"""Coordinate pending Queue 3 entries through planning, execution and acknowledgment."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from typing import Protocol

from spotify_manager.application.queue_3_composers import ComposerReader
from spotify_manager.application.queue_3_composers import composer_plan
from spotify_manager.application.queue_3_composers import resolve_composer_route
from spotify_manager.application.queue_3_execution import Queue3Execution
from spotify_manager.application.queue_3_execution import Queue3LiveQueue
from spotify_manager.application.queue_3_execution import Queue3Transition
from spotify_manager.application.queue_3_planner import Queue3Planner
from spotify_manager.application.queue_3_run import Queue3Run
from spotify_manager.application.queue_3_run import Queue3Snapshot
from spotify_manager.application.queue_3_state import result_from_plan
from spotify_manager.application.queue_3_state import source_from_record
from spotify_manager.application.queue_3_values import FlushResult
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.composers import is_composer_playlist_candidate


class ReviewPresentation(Protocol):
    """Present Queue 3 entry progress and stale-plan removal at original boundaries."""

    def started(self, index: int, total: int, artist: str, track: str) -> None:
        """Report progress before preparing this entry's plan.

        Args:
            index: One-based snapshot entry position.
            total: Original complete snapshot size.
            artist: Logical artist name.
            track: Original source marker title.
        """

    def finished(self, index: int, total: int, artist: str) -> None:
        """Report progress after audit and acknowledgment.

        Args:
            index: One-based snapshot entry position.
            total: Original complete snapshot size.
            artist: Logical artist name.
        """

    def stale(self, artist: str) -> None:
        """Report stale composer-plan removal before its checkpoint.

        Args:
            artist: Logical artist name.
        """


@dataclass
class Queue3Observations:
    """Cache catalogs and works playlists only within this review invocation.

    Args:
        read_catalog: Original eligible studio catalog reader.
        read_works: Original parsed playlist reader with Queue 3 error translation.
        catalogs: Already observed logical-artist catalogs.
        works: Already observed owned works-playlist markers.
    """

    read_catalog: Callable[[str], tuple[DiscographyRelease, ...]]
    read_works: Callable[[str], tuple[PlaylistTrack, ...]]
    catalogs: dict[str, tuple[DiscographyRelease, ...]] = field(default_factory=dict)
    works: dict[str, tuple[PlaylistTrack, ...]] = field(default_factory=dict)

    def catalog(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Observe an artist's catalog once, including empty observations.

        Args:
            artist_id: Original logical artist identifier.

        Returns:
            Cached or newly observed chronological selected editions.
        """
        found = self.catalogs.get(artist_id)
        if found is None:
            found = self.read_catalog(artist_id)
            self.catalogs[artist_id] = found
        return found

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe an owned works playlist once, including empty observations.

        Args:
            playlist_id: Accepted owned playlist identifier.

        Returns:
            Cached or newly observed works in original playlist order.
        """
        found = self.works.get(playlist_id)
        if found is None:
            found = self.read_works(playlist_id)
            self.works[playlist_id] = found
        return found


@dataclass(frozen=True)
class Queue3Entry:
    """Decoded logical artist and mutable record for a pending snapshot entry.

    Args:
        source: Original source marker.
        artist_id: Original logical identifier with primary-credit fallback.
        artist_name: Original logical name with primary-credit fallback.
        record: Mutable durable entry awaiting acknowledgment.
    """

    source: PlaylistTrack
    artist_id: str
    artist_name: str
    record: dict[str, object]


@dataclass(frozen=True)
class Queue3Review:
    """Own entry decisions and original plan, audit and checkpoint ordering.

    Args:
        session: Current namespace, clock and checkpoint ownership.
        snapshot: Validated original run records.
        queue: Observed queue and shared live-ID projection.
        planner: Chronological planner with original track/like caches.
        execution: Saved-plan executor and library reconciliation.
        observations: Run-scoped catalogs and works playlist observations.
        owned: Original owned playlists used to revalidate composer routes.
        choose_composer: Optional original composer selection callback.
        audit: Original transition audit boundary.
        presentation: Existing progress and stale-plan messages.
    """

    session: Queue3Run
    snapshot: Queue3Snapshot
    queue: Queue3LiveQueue
    planner: Queue3Planner
    execution: Queue3Execution
    observations: Queue3Observations
    owned: tuple[OwnedPlaylist, ...]
    choose_composer: ComposerReader | None
    audit: Callable[[str, dict[str, object]], None]
    presentation: ReviewPresentation

    def run(self) -> tuple[tuple[FlushResult, ...], bool]:
        """Process pending entries until the operator pauses or review finishes.

        Returns:
            Public results from this invocation and whether review paused.

        Raises:
            Queue3StateError: A pending entry or durable record is malformed.
            Queue3Error: Planning or execution rejects configuration or live facts.
            OSError: An effect fails; earlier accepted effects are retained.
        """
        results: list[FlushResult] = []
        for index, raw in enumerate(self.snapshot.entries, start=1):
            result = self._entry(raw, index)
            if result == "pause":
                return tuple(results), True
            if isinstance(result, FlushResult):
                results.append(result)
        return tuple(results), False

    def _entry(self, raw: object, index: int) -> FlushResult | Literal["skip", "pause"]:
        if not isinstance(raw, dict):
            raise Queue3StateError("Queue 3 run contains an invalid entry.")
        if raw.get("status") in {"completed", "skipped"}:
            return "skip"
        entry = _decode(raw)
        total = len(self.snapshot.entries)
        self.presentation.started(index, total, entry.artist_name, entry.source.name)
        plan = self._plan(entry)
        if plan is None:
            return "pause"
        transition = Queue3Transition(
            entry.source, entry.artist_id, entry.artist_name, plan
        )
        action, target = self.execution.run(transition, self.queue)
        result = result_from_plan(
            entry.source,
            plan,
            artist_name=entry.artist_name,
            dry_run=self.session.dry_run,
        )
        self.audit(
            "artist_transition", {"run_id": self.snapshot.identifier, **asdict(result)}
        )
        self.session.acknowledge(
            raw, action, target, entry.artist_id, self.snapshot.routes
        )
        self.presentation.finished(index, total, entry.artist_name)
        return result

    def _plan(self, entry: Queue3Entry) -> dict[str, object] | None:
        saved = self._saved_plan(entry)
        if saved is not None:
            return saved
        plan = self._new_plan(entry)
        if plan is None:
            return None
        entry.record["plan"] = plan
        self.session.save()
        return plan

    def _saved_plan(self, entry: Queue3Entry) -> dict[str, object] | None:
        raw = entry.record.get("plan")
        if not isinstance(raw, dict):
            return None
        if not raw.get("composer_playlist_id"):
            return raw
        valid = is_composer_playlist_candidate(
            entry.artist_name,
            str(raw["composer_playlist_id"]),
            self.owned,
            excluded_playlist_ids=frozenset({self.queue.playlist_id}),
        )
        if valid:
            return raw
        entry.record["plan"] = None
        self.snapshot.routes.pop(entry.artist_id, None)
        self.presentation.stale(entry.artist_name)
        self.session.save()
        return None

    def _new_plan(self, entry: Queue3Entry) -> dict[str, object] | None:
        playlist, paused = resolve_composer_route(
            entry.artist_id,
            entry.artist_name,
            entry.source.spotify_id,
            self.queue.playlist_id,
            self.owned,
            self.session.state,
            self.choose_composer,
            self.session.timestamp,
        )
        if paused:
            return None
        if playlist is not None:
            tracks = self.observations.playlist(playlist.spotify_id)
            return composer_plan(entry.source, playlist, tracks)
        catalog = self.observations.catalog(entry.artist_id)
        return self.planner.plan(entry.source, catalog)


def _decode(raw: dict[str, object]) -> Queue3Entry:
    source = source_from_record(raw.get("source"))
    return Queue3Entry(
        source,
        str(raw.get("artist_id") or source.primary_artist_id),
        str(raw.get("artist_name") or source.primary_artist_name),
        raw,
    )
