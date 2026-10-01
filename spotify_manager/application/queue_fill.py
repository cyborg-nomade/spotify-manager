"""Gather Queue fill facts before ordered interaction and accepted execution."""

from dataclasses import dataclass
from datetime import datetime

from spotify_manager.application.queue_fill_candidates import QueueFillCandidates
from spotify_manager.application.queue_fill_effects import QueueFillEffects
from spotify_manager.application.queue_fill_values import FillSummary
from spotify_manager.application.queue_fill_values import QueueFillFacts
from spotify_manager.application.queue_fill_values import QueueFillRequest
from spotify_manager.application.queue_values import QueueConfigError
from spotify_manager.domain.queue_fill import requested_additions
from spotify_manager.domain.queue_history import aggregate_artists


def validate_fill_request(request: QueueFillRequest) -> None:
    """Reject original conflicting or invalid limits before observing dependencies.

    Args:
        request: Original Queue fill limits.

    Raises:
        QueueConfigError: Original limits conflict or are below one.
    """
    if request.count is not None and request.maximum_length is not None:
        raise QueueConfigError("Use either count or maximum playlist length, not both.")
    if request.count is not None and request.count < 1:
        raise QueueConfigError("Count must be at least 1.")
    if request.maximum_length is not None and request.maximum_length < 1:
        raise QueueConfigError("Maximum playlist length must be at least 1.")


def _summary(
    request: QueueFillRequest,
    facts: QueueFillFacts,
    seeds: int,
    candidates: int,
    processed: QueueFillCandidates | None,
) -> FillSummary:
    selected = processed.selected if processed is not None else 0
    after = facts.before if request.preview else facts.before + selected
    return FillSummary(
        week_start=facts.week,
        requested_count=facts.requested,
        history_artists=len(facts.history),
        history_scrobbles=facts.plays,
        live_scrobbles_added=facts.live_added,
        seed_count=seeds,
        candidate_count=candidates,
        playlist_length_before=facts.before,
        playlist_length_after=after,
        paused=processed.paused if processed else False,
        dry_run=request.preview,
        results=tuple(processed.results) if processed else (),
    )


@dataclass(frozen=True)
class QueueFill:
    """Coordinate the original fill's validation, gathering and ordered execution.

    Args:
        effects: Original caller-owned boundary dependencies.
        default_count: Original configured default additions.
        candidate_multiplier: Original candidate pool and examination multiplier.
        minimum_candidates: Original minimum gathering pool.
        top_track_limit: Original top-track window.
    """

    effects: QueueFillEffects
    default_count: int = 20
    candidate_multiplier: int = 10
    minimum_candidates: int = 100
    top_track_limit: int = 10

    def run(self, request: QueueFillRequest) -> FillSummary:
        """Preserve original preview learning and accepted-effect failure boundaries.

        Args:
            request: Original mutually exclusive fill limits and preview behavior.

        Returns:
            Original complete ordered fill summary.

        Raises:
            QueueConfigError: Original requested limits are invalid.
            QueueStateError: Original history, cache or state is unusable.
            QueueSpotifyError: Original membership response is invalid.
        """
        validate_fill_request(request)
        self.effects.configure()
        now, facts = self._facts(request)
        if not facts.requested:
            return _summary(request, facts, 0, 0, None)
        seeds = self.effects.seeds(facts.history, request.seed_count, facts.week)
        candidates = self.effects.candidates(
            seeds,
            {artist.key for artist in facts.history},
            facts.week,
            max(self.minimum_candidates, facts.requested * self.candidate_multiplier),
            now,
        )
        processed = self._processor(request.preview)
        processed.run(candidates, facts.requested)
        return _summary(request, facts, len(seeds), len(candidates), processed)

    def _facts(self, request: QueueFillRequest) -> tuple[datetime, QueueFillFacts]:
        now = self.effects.clock()
        week = self.effects.week(now)
        plays, added = self.effects.history(request.preview, now)
        history = aggregate_artists(plays)
        before = self.effects.queue_length()
        requested = requested_additions(
            request.count, request.maximum_length, before, self.default_count
        )
        return now, QueueFillFacts(week, history, len(plays), added, before, requested)

    def _processor(self, preview: bool) -> QueueFillCandidates:
        represented = self.effects.represented()
        access = self.effects.state()
        state = access.load()
        mappings = state["artist_mappings"]
        assert isinstance(mappings, dict)
        return QueueFillCandidates(
            self.effects,
            access,
            state,
            mappings,
            represented,
            preview,
            multiplier=self.candidate_multiplier,
            top_track_limit=self.top_track_limit,
        )
