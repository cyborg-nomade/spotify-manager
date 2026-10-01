"""Open, resume and checkpoint Queue flush plans at original effect boundaries."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from spotify_manager.application.queue_flush_effects import QueueFlushEffects
from spotify_manager.application.queue_flush_execution import QueueFlushExecution
from spotify_manager.application.queue_flush_values import FlushResult
from spotify_manager.application.queue_flush_values import FlushSummary
from spotify_manager.application.queue_flush_values import QueueFlushFacts
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.queue_flush import daily_sources
from spotify_manager.domain.queue_flush import source_uris


def new_flush_run(
    playlist: str,
    tracks: tuple[PlaylistTrack, ...],
    limit: int,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Snapshot original daily sources and retain the two distinct clock reads.

    Args:
        playlist: Original Queue identity.
        tracks: Original live Queue observations.
        limit: Original configured distinct-artist limit.
        clock: Original UTC clock boundary.

    Returns:
        Original mutable run document with pending entries.
    """
    selected = daily_sources(tracks, limit)
    run_id = clock().strftime("%Y%m%dT%H%M%S%fZ")
    started_at = clock().isoformat()
    entries: list[dict[str, object]] = []
    for track in selected:
        entries.append({"source": asdict(track), "status": "pending", "plan": None})
    return {
        "run_id": run_id,
        "playlist_id": playlist,
        "started_at": started_at,
        "entries": entries,
    }


@dataclass(frozen=True)
class QueueFlush:
    """Preserve original live reads, stored-plan authority and accepted checkpoints.

    Args:
        effects: Original caller-owned storage, catalog and effect boundaries.
    """

    effects: QueueFlushEffects

    def run(self, preview: bool) -> FlushSummary:
        """Open or resume the original daily snapshot and process unfinished entries.

        Args:
            preview: Original preview behavior.

        Returns:
            Original complete ordered flush outcome.

        Raises:
            QueueStateError: Original stored entries, sources or plans are invalid.
            QueueSpotifyError: Original follow-status response is invalid.
        """
        self.effects.configure()
        access = self.effects.state()
        state = self.effects.default_state() if preview else access.load()
        facts = self._facts(access, state, preview)
        execution = QueueFlushExecution(self.effects, facts, preview)
        results: list[FlushResult] = []
        total = len(facts.entries)
        for index, raw in enumerate(facts.entries, start=1):
            result = self._entry(raw, index, total, access, state, facts, execution)
            if result is not None:
                results.append(result)
        if not preview:
            state["active_flush"] = None
            access.save(state)
        return FlushSummary(
            str(facts.run.get("run_id") or "dry-run"),
            len(facts.tracks),
            len(facts.live_uris),
            total,
            len(results),
            facts.resumed,
            preview,
            tuple(results),
        )

    def _facts(
        self,
        access: QueueStateAccess,
        state: dict[str, object],
        preview: bool,
    ) -> QueueFlushFacts:
        active = state.get("active_flush")
        resumed = bool(
            not preview
            and isinstance(active, dict)
            and active.get("playlist_id") == self.effects.queue_id()
        )
        tracks = self.effects.queue()
        run = (
            cast(dict[str, object], active) if resumed else self.effects.new_run(tracks)
        )
        if not resumed and not preview:
            state["active_flush"] = run
            access.save(state)
        entries = run.get("entries")
        if not isinstance(entries, list):
            raise QueueStateError("Queue active flush has invalid entries.")
        return QueueFlushFacts(
            run,
            entries,
            tracks,
            {track.spotify_id for track in tracks},
            {track.uri for track in tracks},
            self.effects.queue_2(),
            self.effects.unlucky(),
            resumed,
        )

    def _entry(
        self,
        raw: object,
        index: int,
        total: int,
        access: QueueStateAccess,
        state: dict[str, object],
        facts: QueueFlushFacts,
        execution: QueueFlushExecution,
    ) -> FlushResult | None:
        if not isinstance(raw, dict):
            raise QueueStateError("Queue active flush has an invalid entry.")
        if raw.get("status") == "completed":
            return None
        source = self.effects.decode_source(raw.get("source"))
        self.effects.progress(
            index - 1, total, f"Planning {source.primary_artist_name}"
        )
        plan = self._plan(raw, source, access, state, facts, execution.preview)
        execution.run(source, plan)
        result = self.effects.result(source, plan, execution.preview)
        self.effects.audit(facts.run, source, result)
        if not execution.preview:
            raw["status"] = "completed"
            access.save(state)
        self.effects.progress(index, total, f"Completed {source.primary_artist_name}")
        return result

    def _plan(
        self,
        entry: dict[str, object],
        source: PlaylistTrack,
        access: QueueStateAccess,
        state: dict[str, object],
        facts: QueueFlushFacts,
        preview: bool,
    ) -> dict[str, object]:
        raw_plan = entry.get("plan")
        if isinstance(raw_plan, dict):
            return raw_plan
        plan = self.effects.plan(source, source_uris(facts.tracks, source))
        entry["plan"] = plan
        if not preview:
            access.save(state)
        return plan
