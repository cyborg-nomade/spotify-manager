"""Plan New Wine transitions at the original observation and interaction boundaries."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass

from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.new_wine_plans import drop_plan
from spotify_manager.application.new_wine_plans import progression_plan
from spotify_manager.application.new_wine_plans import record_evaluation
from spotify_manager.application.new_wine_values import EndpointChoiceReader
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.new_wine_values import NewWineError
from spotify_manager.application.new_wine_values import ReleaseChoiceReader
from spotify_manager.application.ports.new_wine import NewWinePresentation
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.new_wine import selected_transition
from spotify_manager.domain.new_wine import track_index
from spotify_manager.domain.progression import advance_streak
from spotify_manager.domain.progression import next_liked_track
from spotify_manager.domain.progression import trailing_unliked


type WineDecision = dict[str, object] | FlushResult | None


@dataclass
class SourceObservations:
    """Current source facts and the operator's existing canonical endpoint choice.

    Args:
        source: Original playlist marker.
        entry: Mutable durable entry owning the endpoint choice.
        tracks: Original canonical tracks, truncated only after an accepted cutoff.
        index: Source position within the preferred track list, if mapped.
        liked: Current source membership.
        streak: Streak after the source observation.
        endpoint: Existing or newly accepted endpoint choice.
    """

    source: PlaylistTrack
    entry: dict[str, object]
    tracks: tuple[ReleaseTrack, ...]
    index: int | None
    liked: bool
    streak: int
    endpoint: object


@dataclass
class WinePlanner:
    """Own one run's observations, choice callbacks and endpoint checkpoints.

    Args:
        observations: Run-scoped catalog and membership cache.
        progress: Original persisted source streak records.
        choose: Existing release-choice callback.
        endpoint_reader: Optional endpoint callback, required when mode is active.
        endpoint_mode: Whether to ask for album/EP endpoints.
        dry_run: Whether skip results describe a preview.
        checkpoint: Callback saving accepted endpoint choices at the original boundary.
        presentation: Existing planning messages rendered at their original boundaries.
    """

    observations: WineObservations
    progress: dict[str, object]
    choose: ReleaseChoiceReader
    endpoint_reader: EndpointChoiceReader | None
    endpoint_mode: bool
    dry_run: bool
    checkpoint: Callable[[], None]
    presentation: NewWinePresentation

    def plan(self, source: PlaylistTrack, entry: dict[str, object]) -> WineDecision:
        """Plan one source, returning a skip result or pause at the original boundary.

        Args:
            source: Original playlist marker.
            entry: Its current durable record.

        Returns:
            Durable plan, explicit skip result, or None for an operator pause.

        Raises:
            NewWineError: The operator selects an unavailable release or endpoint.
        """
        facts = self._facts(source, entry)
        endpoint = self._endpoint(facts)
        if endpoint == "quit":
            return None
        if endpoint == "skip":
            return self._skip(facts, source.release)
        decision = self._primary(facts)
        if not isinstance(decision, dict):
            return decision
        if facts.endpoint == "cutoff":
            decision["canonical_track_count"] = len(facts.tracks)
            decision["canonical_cutoff_track"] = source.name
        return self._continuation(facts, decision)

    def _facts(
        self, source: PlaylistTrack, entry: dict[str, object]
    ) -> SourceObservations:
        tracks = self.observations.tracks(source.release)
        index = track_index(tracks, source)
        endpoint = entry.get("endpoint_choice")
        liked = self.observations.source_liked(source.spotify_id)
        prior = self._prior_streak(source, tracks, index)
        return SourceObservations(
            source, entry, tracks, index, liked, advance_streak(prior, liked), endpoint
        )

    def _prior_streak(
        self, source: PlaylistTrack, tracks: tuple[ReleaseTrack, ...], index: int | None
    ) -> int:
        stored = self.progress.get(source.spotify_id)
        prior = stored.get("prior_unliked_streak") if isinstance(stored, dict) else None
        if isinstance(prior, int):
            return prior
        if index is None:
            return 0
        preceding = tracks[:index]
        self.observations.memberships(preceding)
        return trailing_unliked(
            self.observations.liked[track.spotify_id] for track in reversed(preceding)
        )

    def _endpoint(self, facts: SourceObservations) -> str:
        if (
            not self.endpoint_mode
            or facts.source.release.release_type not in {"Album", "EP"}
            or facts.index is None
        ):
            return "continue"
        if facts.endpoint not in {"cutoff", "continue"}:
            choice = self._choose_endpoint(facts)
            if choice == "quit" or choice == "skip":
                return choice
        if facts.endpoint == "cutoff":
            facts.tracks = facts.tracks[: facts.index + 1]
            self.presentation.canonical(facts.source, len(facts.tracks))
        return "continue"

    def _choose_endpoint(self, facts: SourceObservations) -> str:
        assert self.endpoint_reader is not None and facts.index is not None
        choice = self.endpoint_reader(facts.source, facts.tracks, facts.index)
        if choice == "quit" or choice == "skip":
            return choice
        if choice not in {"cutoff", "continue"}:
            raise NewWineError("The album endpoint choice is not available.")
        facts.endpoint = choice
        facts.entry["endpoint_choice"] = choice
        self.checkpoint()
        return choice

    def _primary(self, facts: SourceObservations) -> WineDecision:
        if facts.streak >= 3:
            return self._streak_plan(facts)
        selected = self._select_release(facts)
        if not isinstance(selected, ReleaseCandidate):
            return selected
        tracks = self.observations.tracks(selected)
        if (
            selected.spotify_id == facts.source.release.spotify_id
            and facts.endpoint == "cutoff"
            and facts.index is not None
        ):
            tracks = tracks[: facts.index + 1]
        if not tracks:
            self.presentation.empty(selected)
            return self._skip(facts, selected)
        return self._selected_plan(facts, selected, tracks)

    def _streak_plan(self, facts: SourceObservations) -> dict[str, object]:
        self.observations.memberships(facts.tracks)
        target = next_liked_track(facts.tracks, facts.index, self.observations.liked)
        if target is not None:
            return progression_plan(
                "advance",
                facts.source.release,
                target,
                facts.liked,
                facts.streak,
                next_liked=True,
            )
        return self._drop(facts, "three_consecutive_unliked")

    def _drop(self, facts: SourceObservations, reason: str) -> dict[str, object]:
        evaluation = evaluate_release(
            facts.source.release, facts.tracks, self.observations.liked
        )
        return drop_plan(
            facts.source.release,
            evaluation,
            current_liked=facts.liked,
            consecutive_unliked=facts.streak,
            reason=reason,
        )

    def _select_release(
        self, facts: SourceObservations
    ) -> ReleaseCandidate | WineDecision:
        if facts.source.release.release_type != "Single":
            return facts.source.release
        candidates = self.observations.releases(facts.source.primary_artist_id)
        if not candidates:
            self.presentation.no_releases(facts.source, self.observations.year)
            return self._skip(facts, facts.source.release)
        choice, reason = self._single_choice(facts, candidates)
        if choice == "quit":
            return None
        if choice == "skip":
            return self._skip(facts, facts.source.release)
        if choice == "drop":
            self.observations.memberships(facts.tracks)
            return self._drop(facts, reason)
        return _selected(candidates, choice)

    def _single_choice(
        self, facts: SourceObservations, candidates: tuple[ReleaseCandidate, ...]
    ) -> tuple[str, str]:
        if (
            len(candidates) == 1
            and candidates[0].spotify_id == facts.source.release.spotify_id
            and candidates[0].release_type == "Single"
        ):
            self.presentation.only_single(facts.source, self.observations.year)
            return "drop", "only_current_year_single"
        return self.choose(facts.source, candidates), "manual_selection"

    def _selected_plan(
        self,
        facts: SourceObservations,
        release: ReleaseCandidate,
        tracks: tuple[ReleaseTrack, ...],
    ) -> dict[str, object]:
        action, target = selected_transition(facts.source, release, tracks)
        plan = progression_plan(action, release, target, facts.liked, facts.streak)
        if action == "sauvignon":
            self.observations.memberships(tracks)
            record_evaluation(
                plan, evaluate_release(release, tracks, self.observations.liked)
            )
        return plan

    def _continuation(
        self, facts: SourceObservations, plan: dict[str, object]
    ) -> WineDecision:
        if str(plan["action"]) not in {
            "drop",
            "sauvignon",
        } or facts.source.release.release_type not in {"Album", "EP"}:
            return plan
        releases = self.observations.releases(facts.source.primary_artist_id)
        candidates = _other_releases(releases, facts.source.release.spotify_id)
        if not candidates:
            return plan
        choice = self.choose(facts.source, candidates)
        if choice == "quit":
            return None
        if choice == "skip":
            return self._skip(facts, facts.source.release)
        if choice in {"finish", "drop"}:
            return plan
        release = _selected(candidates, choice)
        tracks = self.observations.tracks(release)
        if tracks:
            plan["continuation_release"] = asdict(release)
            plan["continuation_target"] = asdict(tracks[0])
        else:
            self.presentation.empty_continuation(release)
        return plan

    def _skip(
        self, facts: SourceObservations, release: ReleaseCandidate
    ) -> FlushResult:
        return FlushResult(
            source_track=facts.source.name,
            artist=facts.source.primary_artist_name,
            release=release.name,
            release_type=release.release_type,
            current_liked=facts.liked,
            consecutive_unliked=facts.streak,
            action="skip",
            dry_run=self.dry_run,
        )


def _selected(
    candidates: tuple[ReleaseCandidate, ...], choice: str
) -> ReleaseCandidate:
    for candidate in candidates:
        if candidate.spotify_id == choice:
            return candidate
    raise NewWineError("The selected release is not available.")


def _other_releases(
    candidates: tuple[ReleaseCandidate, ...], source_id: str
) -> tuple[ReleaseCandidate, ...]:
    others = []
    for candidate in candidates:
        if candidate.spotify_id != source_id:
            others.append(candidate)
    return tuple(others)
