"""Execute saved Queue 3 transitions at the original accepted-effect boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.queue_3_state import release_from_record
from spotify_manager.application.queue_3_state import track_from_record
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.catalog import release_candidate
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.queue_3 import ranked_release
from spotify_manager.models.lookups import AlbumEvaluation


class ExecutionPresentation(Protocol):
    """Report playlist effects only after their original acceptance boundaries."""

    def added(self, name: str, dry_run: bool) -> None:
        """Report a new target marker.

        Args:
            name: Target title.
            dry_run: Whether the effect is projected.
        """

    def removed(self, name: str, dry_run: bool) -> None:
        """Report removal of a previous marker.

        Args:
            name: Original source title.
            dry_run: Whether the effect is projected.
        """

    def completed(self, artist: str, dry_run: bool) -> None:
        """Report the end of an artist's catalog.

        Args:
            artist: Original logical artist display name.
            dry_run: Whether the effect is projected.
        """

    def skipped(self, artist: str, reason: object) -> None:
        """Report an unmapped marker.

        Args:
            artist: Original logical artist display name.
            reason: Original reason, including its tolerant string representation.
        """


@dataclass(frozen=True)
class Queue3Transition:
    """One snapshotted logical artist and its accepted durable plan.

    Args:
        source: Original marker.
        artist_id: Logical artist identifier used for ordinary queue cleanup.
        artist_name: Logical display name used for effects and messages.
        plan: Original durable transition record.
    """

    source: PlaylistTrack
    artist_id: str
    artist_name: str
    plan: dict[str, object]


@dataclass
class Queue3LiveQueue:
    """Retain the original observed marker list and mutable live-ID projection.

    Args:
        playlist_id: Queue 3 destination.
        tracks: Original markers, including accepted annual import projections.
        ids: Live membership projection shared between artist entries.
    """

    playlist_id: str
    tracks: list[PlaylistTrack]
    ids: set[str]

    def artist_uris(self, transition: Queue3Transition) -> list[str]:
        """Select original cleanup markers, restricting composer routes to the source.

        Args:
            transition: Artist and saved route being executed.

        Returns:
            Original ordered URI list, retaining duplicates for the adapter to batch.
        """
        source = transition.source
        if bool(transition.plan.get("composer_playlist_id")):
            return [source.uri] if source.spotify_id in self.ids else []
        uris: list[str] = []
        for track in self.tracks:
            if (
                track.primary_artist_id == transition.artist_id
                and track.spotify_id in self.ids
            ):
                uris.append(track.uri)
        return uris

    def removed(self, uris: list[str]) -> None:
        """Update IDs using the original snapshot, without rewriting its marker list.

        Args:
            uris: Original artist cleanup selection, excluding any fallback URI.
        """
        selected = set(uris)
        for track in self.tracks:
            if track.uri in selected:
                self.ids.discard(track.spotify_id)


@dataclass(frozen=True)
class Queue3Execution:
    """Reconcile library membership before replacing or completing playlist markers.

    Args:
        append: Original ordered playlist append boundary.
        remove: Original URI deduplication and removal boundary.
        reconcile: Shared release library workflow with the original audit destination.
        presentation: Existing effect messages.
        dry_run: Whether to suppress mutations while retaining projections and messages.
    """

    append: Callable[[str, list[PlaylistTrack], str], None]
    remove: Callable[[str, list[str], str], None]
    reconcile: Callable[[RankedRelease, AlbumEvaluation], str]
    presentation: ExecutionPresentation
    dry_run: bool

    def run(
        self, transition: Queue3Transition, queue: Queue3LiveQueue
    ) -> tuple[str, ReleaseTrack | None]:
        """Execute a saved transition without acknowledging its audit or checkpoint.

        Args:
            transition: Snapshotted artist and accepted durable plan.
            queue: Original live observations and shared mutable ID projection.

        Returns:
            Original action and decoded target for the coordinator's acknowledgment.

        Raises:
            Queue3StateError: Saved records are invalid or both replacement markers
                are absent, or a new target has no saved release.
            TypeError: Saved constructor fields are invalid.
            ValidationError: A stored evaluation is invalid.
            OSError: An injected boundary fails; prior accepted effects remain.
        """
        plan = transition.plan
        action = str(plan["action"])
        current = release_from_record(plan.get("current_release"))
        target_release = release_from_record(plan.get("target_release"))
        target = track_from_record(plan.get("target"))
        evaluation = _evaluation(plan.get("evaluation"))
        if evaluation is not None and current is not None:
            self.reconcile(ranked_release(current), evaluation)
        uris = queue.artist_uris(transition)
        if (
            action in {"advance", "composer_advance", "next_release"}
            and target is not None
        ):
            self._advance(transition, queue, target, target_release or current, uris)
        elif action == "complete":
            self._complete(transition, queue, uris)
        elif action == "skip":
            self.presentation.skipped(transition.artist_name, plan.get("reason"))
        return action, target

    def _advance(
        self,
        transition: Queue3Transition,
        queue: Queue3LiveQueue,
        target: ReleaseTrack,
        release: DiscographyRelease | None,
        uris: list[str],
    ) -> None:
        source = transition.source
        source_present = source.spotify_id in queue.ids
        target_present = target.spotify_id in queue.ids
        if not source_present and not target_present:
            raise Queue3StateError(
                f"{source.name} and its planned replacement are both absent."
            )
        if not target_present:
            self._add(transition, queue, target, release)
        if not source_present and not uris:
            return
        if not self.dry_run:
            self.remove(
                queue.playlist_id,
                uris or [source.uri],
                f"removing the previous {transition.artist_name} marker",
            )
        queue.removed(uris)
        self.presentation.removed(source.name, self.dry_run)

    def _add(
        self,
        transition: Queue3Transition,
        queue: Queue3LiveQueue,
        target: ReleaseTrack,
        release: DiscographyRelease | None,
    ) -> None:
        if release is None:
            raise Queue3StateError(f"{target.name} has no saved target release.")
        if not self.dry_run:
            marker = _target_marker(transition, target, release)
            self.append(queue.playlist_id, [marker], f"adding {target.name} to Queue 3")
        queue.ids.add(target.spotify_id)
        self.presentation.added(target.name, self.dry_run)

    def _complete(
        self,
        transition: Queue3Transition,
        queue: Queue3LiveQueue,
        uris: list[str],
    ) -> None:
        if uris:
            self._remove_completed(transition, queue, uris)
        self.presentation.completed(transition.artist_name, self.dry_run)

    def _remove_completed(
        self,
        transition: Queue3Transition,
        queue: Queue3LiveQueue,
        uris: list[str],
    ) -> None:
        if not self.dry_run:
            self.remove(
                queue.playlist_id,
                uris,
                f"completing {transition.artist_name} in Queue 3",
            )
        queue.removed(uris)


def _evaluation(raw: object) -> AlbumEvaluation | None:
    return AlbumEvaluation.model_validate(raw) if isinstance(raw, dict) else None


def _target_marker(
    transition: Queue3Transition,
    target: ReleaseTrack,
    release: DiscographyRelease,
) -> PlaylistTrack:
    candidate = release_candidate(release)
    return PlaylistTrack(
        target.spotify_id,
        target.uri,
        target.name,
        transition.artist_id,
        transition.artist_name,
        candidate,
    )
