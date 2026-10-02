"""Plan automatic track advances and prompted chronological release transitions."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass

from spotify_manager.application.queue_3_values import Queue3Error
from spotify_manager.application.slow_listening_plan import ReleaseOrdering
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.queue_3 import source_release
from spotify_manager.domain.slow_listening import track_index
from spotify_manager.models.lookups import AlbumEvaluation


type TransitionReader = Callable[
    [PlaylistTrack, DiscographyRelease, DiscographyRelease], str
]


def stable_release_order(
    _date: str, releases: tuple[DiscographyRelease, ...]
) -> tuple[str, ...]:
    """Accept catalog order for equal-date releases without an additional prompt.

    Args:
        _date: Existing ordering callback's date label.
        releases: Releases tied on chronology in observed catalog order.

    Returns:
        Identifiers in the unchanged catalog order.
    """
    return tuple(release.spotify_id for release in releases)


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
        read: Observe tracks through the original retry boundary.
        evaluate: Observe live liked statuses and apply the original album policy.
        tracks: Caller-owned track cache, retaining empty observations.
        ordering: Shared chronological ordering and checkpoint rules.
        choose: Original release-boundary callback.
    """

    read: Callable[[DiscographyRelease], tuple[ReleaseTrack, ...]]
    evaluate: Callable[[DiscographyRelease, tuple[ReleaseTrack, ...]], AlbumEvaluation]
    tracks: dict[str, tuple[ReleaseTrack, ...]]
    ordering: ReleaseOrdering
    choose: TransitionReader

    def plan(
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
            return self._ineligible(source, discography)
        tracks = self._tracks(current)
        index = track_index(tracks, source)
        if index is None:
            return self._unmapped(current, tracks)
        if index + 1 < len(tracks):
            return _plan("advance", current, current, tracks[index + 1], None, None)
        evaluation = self.evaluate(current, tracks)
        following = self.ordering.following(current, discography)
        if following is None:
            return _plan(
                "complete",
                current,
                None,
                None,
                evaluation,
                "last track of the final studio release",
            )
        return self.transition(source, current, following, evaluation=evaluation)

    def transition(
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
        choice = self.choose(source, current, following)
        if choice == "quit":
            return None
        if choice != "advance":
            raise Queue3Error("Release transition must be advance or quit.")
        tracks = self._tracks(following)
        if not tracks:
            raise Queue3Error(f"{following.name} has no playable tracks.")
        return _plan("next_release", current, following, tracks[0], evaluation, reason)

    def _tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        tracks = self.tracks.get(release.spotify_id)
        if tracks is None:
            tracks = self.read(release)
            self.tracks[release.spotify_id] = tracks
        return tracks

    def _ineligible(
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
        return self.transition(
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
