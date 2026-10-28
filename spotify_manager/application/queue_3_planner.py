"""Plan automatic track advances and prompted chronological release transitions."""

from dataclasses import asdict
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.queue_3_values import Queue3Error
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.catalog import release_candidate
from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.queue_3 import source_release
from spotify_manager.domain.slow_listening import track_index
from spotify_manager.models.lookups import AlbumEvaluation


class TransitionReader(Protocol):
    """Own the operator interaction for choose transition."""

    async def choose_transition(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            current: Original interaction value.
            following: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class Queue3Catalog(Protocol):
    """Read ordered studio tracks and their live liked membership."""

    async def release_tracks(
        self, release: DiscographyRelease
    ) -> tuple[ReleaseTrack, ...]:
        """Read the selected edition's ordered tracks.

        Args:
            release: Selected studio edition.

        Returns:
            Original playable tracks.
        """

    async def memberships(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> dict[str, bool]:
        """Read live memberships before applying the album decision.

        Args:
            release: Completed selected edition.
            tracks: Previously observed complete track list.

        Returns:
            Original run-scoped liked statuses.
        """


def _plan(
    action: str,
    current: DiscographyRelease,
    target_release: DiscographyRelease | None,
    target: ReleaseTrack | None,
    evaluation: AlbumEvaluation | None,
    reason: str | None,
) -> dict[str, object]:
    return {
        "action": action,
        "current_release": asdict(current),
        "target_release": asdict(target_release)
        if target_release is not None
        else None,
        "target": asdict(target) if target is not None else None,
        "evaluation": evaluation.model_dump(mode="json")
        if evaluation is not None
        else None,
        "reason": reason,
    }


@dataclass
class Queue3Planner:
    """Reuse run-scoped track facts and persist ordering before prompting transitions.

    Args:
        catalog: Ordered track and liked-membership observations.
        tracks: Caller-owned track cache, retaining empty observations.
        ordering: Shared chronological ordering and checkpoint rules.
        choose: Original release-boundary callback.
    """

    catalog: Queue3Catalog
    tracks: dict[str, tuple[ReleaseTrack, ...]]
    ordering: ReleaseOrdering
    choose: TransitionReader

    async def plan(
        self, source: PlaylistTrack, discography: tuple[DiscographyRelease, ...]
    ) -> dict[str, object] | None:
        """Plan the next track, release boundary, or completed catalog.

        Args:
            source: Current Queue 3 marker.
            discography: Eligible selected editions in chronological order.

        Returns:
            Original durable plan, or None when the operator pauses.

        Raises:
            Queue3Error: The choice is invalid or an accepted successor has no tracks.
            SlowListeningError: Persisted release ordering cannot be resolved.
        """
        current, _following = release_transition(source.release.name, discography)
        if current is None:
            return await self._ineligible(source, discography)
        tracks = await self._tracks(current)
        index = track_index(tracks, source)
        if index is None:
            return self._unmapped(current, tracks)
        if index + 1 < len(tracks):
            return _plan("advance", current, current, tracks[index + 1], None, None)
        liked = await self.catalog.memberships(current, tracks)
        evaluation = evaluate_release(release_candidate(current), tracks, liked)
        following = await self.ordering.following(current, discography)
        if following is None:
            return _plan(
                "complete",
                current,
                None,
                None,
                evaluation,
                "last track of the final studio release",
            )
        return await self.transition(source, current, following, evaluation=evaluation)

    async def transition(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
        *,
        evaluation: AlbumEvaluation | None = None,
        reason: str | None = None,
    ) -> dict[str, object] | None:
        """Prompt before observing an accepted successor's first track.

        Args:
            source: Original Queue 3 marker.
            current: Completed or ineligible current release.
            following: Proposed successor.
            evaluation: Completed current-release evaluation, when available.
            reason: Original explanation for an ineligible source transition.

        Returns:
            Original next-release plan, or None for a quit response.

        Raises:
            Queue3Error: Choice is invalid or the accepted successor has no tracks.
        """
        choice = await self.choose.choose_transition(source, current, following)
        if choice == "quit":
            return None
        if choice != "advance":
            raise Queue3Error("Release transition must be advance or quit.")
        tracks = await self._tracks(following)
        if not tracks:
            raise Queue3Error(f"{following.name} has no playable tracks.")
        return _plan("next_release", current, following, tracks[0], evaluation, reason)

    async def _tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        tracks = self.tracks.get(release.spotify_id)
        if tracks is None:
            tracks = await self.catalog.release_tracks(release)
            self.tracks[release.spotify_id] = tracks
        return tracks

    async def _ineligible(
        self, source: PlaylistTrack, discography: tuple[DiscographyRelease, ...]
    ) -> dict[str, object] | None:
        current = source_release(source)
        if not discography:
            return _plan(
                "complete",
                current,
                None,
                None,
                None,
                "artist has no eligible studio album or EP",
            )
        return await self.transition(
            source,
            current,
            discography[0],
            reason="moved from an ineligible marker to the first studio release",
        )

    def _unmapped(
        self, current: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> dict[str, object]:
        if tracks:
            return _plan(
                "advance",
                current,
                current,
                tracks[0],
                None,
                "restarted the preferred edition at its first track",
            )
        return _plan(
            "complete",
            current,
            None,
            None,
            None,
            "current eligible release has no playable tracks",
        )
