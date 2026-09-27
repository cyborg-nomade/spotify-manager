"""Plan ordinary New Kids/Queue 2 progression over explicit cached observations."""

from dataclasses import asdict
from dataclasses import dataclass

from spotify_manager.application.composer_routes import ReleaseChoiceReader
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.ports.discovery import DiscoveryAudit
from spotify_manager.application.ports.discovery import DiscoveryPlanningPresentation
from spotify_manager.application.release_evaluation import evaluate_catalog_release
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import review_catalog
from spotify_manager.domain.discovery_progression import next_release_options
from spotify_manager.domain.progression import advance_streak
from spotify_manager.domain.progression import next_liked_track
from spotify_manager.domain.progression import trailing_unliked
from spotify_manager.models.lookups import AlbumEvaluation


type ReviewDecision = dict[str, object] | FlushResult | None


@dataclass(frozen=True)
class ReviewSource:
    """Observed source facts gathered at the original pre-planning boundary.

    Args:
        source: Original snapshotted marker.
        artist_id: Logical artist identifier.
        artist_name: Logical artist display name.
        progress: Mutable accepted artist progress.
        catalog: Ranked catalog, possibly prepended with the current release.
        release: Current release matched by ID or adapted from the source.
        tracks: Complete current-release observations, including guest credits.
        primary_tracks: Original ordered tracks credited first to the logical artist.
        source_index: Marker position in primary tracks under the existing title rule.
    """

    source: PlaylistTrack
    artist_id: str
    artist_name: str
    progress: dict[str, object]
    catalog: tuple[RankedRelease, ...]
    release: RankedRelease
    tracks: tuple[CatalogTrack, ...]
    primary_tracks: tuple[CatalogTrack, ...]
    source_index: int | None


@dataclass(frozen=True)
class ReviewFacts:
    """Source context plus live membership and the resulting unliked streak.

    Args:
        context: Original source and catalog facts.
        liked: Observed source membership.
        streak: Resulting streak after observing the source.
    """

    context: ReviewSource
    liked: bool
    streak: int


@dataclass(frozen=True)
class NewKidsPlanner:
    """Own ordinary release decisions, operator choices and historical progress events.

    Args:
        observations: Original run-scoped caches and observation services.
        choose: Existing release-choice callback.
        audit: Original event boundary, including preview writes.
        presentation: Original completion-count message boundary.
        year: Existing active invocation year.
        dry_run: Whether results describe previews.
    """

    observations: DiscoveryObservations
    choose: ReleaseChoiceReader
    audit: DiscoveryAudit
    presentation: DiscoveryPlanningPresentation
    year: int
    dry_run: bool

    def plan(self, context: ReviewSource) -> ReviewDecision:
        """Choose a next track, release or terminal artist outcome.

        Args:
            context: Already observed source/catalog facts and mutable progress.

        Returns:
            Original durable plan, explicit skip result, or None for an operator pause.

        Raises:
            NewKidsError: The selected release is unavailable or has no primary tracks.
        """
        facts = self._facts(context)
        target, reason = self._next_track(facts)
        if target is not None:
            return _advance_plan(facts, target, reason)
        self.observations.memberships([track.spotify_id for track in context.tracks])
        evaluation = evaluate_catalog_release(
            context.release, context.tracks, self.observations.liked
        )
        catalog = review_catalog(context.catalog, self.observations.release_limit)
        played = self.observations.played(catalog)
        self._record_history(facts, played)
        if len(played) >= self.observations.release_limit:
            return self._finish(facts, evaluation)
        options = self._remaining_options(context, catalog, played)
        if not options:
            return self._finish(facts, evaluation)
        return self._select_release(facts, evaluation, options[:10], len(played) + 1)

    def _facts(self, context: ReviewSource) -> ReviewFacts:
        self.observations.memberships([context.source.spotify_id])
        liked = self.observations.liked[context.source.spotify_id]
        raw_prior = context.progress.get("prior_unliked_streak")
        if isinstance(raw_prior, int):
            return ReviewFacts(context, liked, advance_streak(raw_prior, liked))
        prior = 0
        if context.source_index is not None:
            preceding = context.primary_tracks[: context.source_index]
            self.observations.memberships([track.spotify_id for track in preceding])
            prior = trailing_unliked(
                self.observations.liked[track.spotify_id]
                for track in reversed(preceding)
            )
        return ReviewFacts(context, liked, advance_streak(prior, liked))

    def _next_track(self, facts: ReviewFacts) -> tuple[CatalogTrack | None, str]:
        context = facts.context
        if facts.streak >= 3:
            self.observations.memberships(
                [track.spotify_id for track in context.primary_tracks]
            )
            return next_liked_track(
                context.primary_tracks, context.source_index, self.observations.liked
            ), "next liked track"
        index = context.source_index
        if index is not None and index + 1 < len(context.primary_tracks):
            return context.primary_tracks[index + 1], "next track"
        return None, "next track"

    def _record_history(
        self, facts: ReviewFacts, played: tuple[RankedRelease, ...]
    ) -> None:
        context = facts.context
        self.presentation.release_progress(context.artist_name, len(played), self.year)
        self.audit.event(
            "annual_release_progress_checked",
            artist=context.artist_name,
            artist_id=context.artist_id,
            year=self.year,
            played_release_ids=[release.spotify_id for release in played],
            played_release_names=[release.name for release in played],
            dry_run=self.dry_run,
        )

    def _finish(
        self, facts: ReviewFacts, evaluation: AlbumEvaluation
    ) -> dict[str, object]:
        context = facts.context
        assessment = self.observations.assessment(context.artist_id, context.catalog)
        return {
            "action": "finish",
            "result_action": _finish_action(assessment),
            "current_release": asdict(context.release),
            "target_release": None,
            "target": None,
            "current_liked": facts.liked,
            "consecutive_unliked": facts.streak,
            "evaluation": evaluation.model_dump(mode="json"),
            "assessment": asdict(assessment),
        }

    def _remaining_options(
        self,
        context: ReviewSource,
        catalog: tuple[RankedRelease, ...],
        played: tuple[RankedRelease, ...],
    ) -> tuple[RankedRelease, ...]:
        excluded = {release.identity for release in played}
        viable = []
        for release in catalog:
            if (
                release.identity in excluded
                or release.identity == context.release.identity
            ):
                continue
            tracks = self.observations.tracks(release)
            if _primary_track(tracks, context.artist_id) is not None:
                viable.append(release)
        return next_release_options(tuple(viable))

    def _select_release(
        self,
        facts: ReviewFacts,
        evaluation: AlbumEvaluation,
        options: tuple[RankedRelease, ...],
        number: int,
    ) -> ReviewDecision:
        context = facts.context
        choice = self.choose(context.artist_name, options)
        if choice == "__quit__":
            return None
        if choice == "__skip__":
            return self._skip(facts)
        selected = _selected_release(options, choice)
        tracks = self.observations.tracks(selected)
        target = _primary_track(tracks, context.artist_id)
        if target is None:
            raise NewKidsError(f"{selected.name} has no primary-artist tracks.")
        return _next_release_plan(facts, selected, target, evaluation, number)

    def _skip(self, facts: ReviewFacts) -> FlushResult:
        context = facts.context
        return FlushResult(
            artist=context.artist_name,
            source_track=context.source.name,
            source_release=context.source.release.name,
            current_liked=facts.liked,
            consecutive_unliked=facts.streak,
            action="skip",
            dry_run=self.dry_run,
        )


def _advance_plan(
    facts: ReviewFacts, target: CatalogTrack, reason: str
) -> dict[str, object]:
    release = facts.context.release
    return {
        "action": "advance",
        "result_action": "advance",
        "current_release": asdict(release),
        "target_release": asdict(release),
        "target": asdict(target),
        "current_liked": facts.liked,
        "consecutive_unliked": facts.streak,
        "next_prior_unliked_streak": 0
        if reason == "next liked track"
        else facts.streak,
        "advance_reason": reason,
    }


def _finish_action(assessment: ArtistAssessment) -> str:
    if assessment.top_liked_track is None:
        return "unfollowed"
    return "great discovery" if assessment.qualifies else "unlucky"


def _primary_track(
    tracks: tuple[CatalogTrack, ...], artist_id: str
) -> CatalogTrack | None:
    for track in tracks:
        if track.primary_artist_id == artist_id:
            return track
    return None


def _selected_release(options: tuple[RankedRelease, ...], choice: str) -> RankedRelease:
    for release in options:
        if release.spotify_id == choice:
            return release
    raise NewKidsError("Selected release is not available.")


def _next_release_plan(
    facts: ReviewFacts,
    release: RankedRelease,
    target: CatalogTrack,
    evaluation: AlbumEvaluation,
    number: int,
) -> dict[str, object]:
    return {
        "action": "next_release",
        "result_action": "next release",
        "current_release": asdict(facts.context.release),
        "target_release": asdict(release),
        "target": asdict(target),
        "current_liked": facts.liked,
        "consecutive_unliked": facts.streak,
        "next_prior_unliked_streak": 0,
        "release_number": number,
        "evaluation": evaluation.model_dump(mode="json"),
    }
