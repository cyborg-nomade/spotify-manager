"""Original Queue flush observation, checkpoint and ordered mutation boundaries."""

from typing import Protocol

from spotify_manager.application.queue_flush_values import FlushResult
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack


class QueueFlushEffects(Protocol):
    """Original caller-owned storage, catalog, effects and presentation boundaries."""

    def configure(self) -> None:
        """Resolve the original retry boundary before state authority."""

    def state(self) -> QueueStateAccess:
        """Resolve original state authority even during preview.

        Returns:
            Original caller-owned state reader and checkpoint writer.
        """

    def default_state(self) -> dict[str, object]:
        """Create original preview state without reading durable state.

        Returns:
            Original empty versioned state.
        """

    def queue_id(self) -> str:
        """Read the original configured Queue identity.

        Returns:
            Original Queue playlist identity.
        """

    def queue(self) -> tuple[PlaylistTrack, ...]:
        """Read original live Queue membership even when resuming.

        Returns:
            Original ordered live markers.
        """

    def new_run(self, tracks: tuple[PlaylistTrack, ...]) -> dict[str, object]:
        """Create a new original daily snapshot and observe its two clocks.

        Args:
            tracks: Original live source observations.

        Returns:
            Original mutable run with pending entries.
        """

    def queue_2(self) -> set[str]:
        """Read original promotion destination before unlucky membership.

        Returns:
            Original represented primary artist identities.
        """

    def unlucky(self) -> set[str]:
        """Read original unlucky destination after promotion membership.

        Returns:
            Original represented primary artist identities.
        """

    def decode_source(self, raw: object) -> PlaylistTrack:
        """Decode original stored source tolerance and errors.

        Args:
            raw: Original unchecked stored source.

        Returns:
            Original authoritative source marker.
        """

    def decode_target(self, raw: object) -> CatalogTrack | None:
        """Decode original optional target tolerance and errors.

        Args:
            raw: Original unchecked stored target.

        Returns:
            Original target marker or no target.
        """

    def plan(self, source: PlaylistTrack, uris: list[str]) -> dict[str, object]:
        """Read facts and choose the original live plan before checkpointing.

        Args:
            source: Original authoritative source marker.
            uris: Original live or fallback source markers.

        Returns:
            Original compatible mutable plan record.
        """

    def append(
        self, destination: str, source: PlaylistTrack, target: CatalogTrack
    ) -> None:
        """Accept the original destination append with its original retry description.

        Args:
            destination: Queue, Queue 2 or unlucky destination role.
            source: Original authoritative source marker.
            target: Original selected destination marker.
        """

    def following(self, source: PlaylistTrack) -> bool:
        """Read and validate original follow status even during preview.

        Args:
            source: Original authoritative source marker.

        Returns:
            Original first follow status.
        """

    def unfollow(self, source: PlaylistTrack) -> None:
        """Accept original unfollow before local mirror removal.

        Args:
            source: Original authoritative source marker.
        """

    def remove_local(self, source: PlaylistTrack) -> None:
        """Remove original local artist mirrors after accepted unfollow.

        Args:
            source: Original authoritative source marker.
        """

    def remove(self, source: PlaylistTrack, uris: list[str]) -> None:
        """Accept original source removal after destination effects.

        Args:
            source: Original authoritative source marker.
            uris: Original ordered removable URIs.
        """

    def result(
        self, source: PlaylistTrack, plan: dict[str, object], preview: bool
    ) -> FlushResult:
        """Decode original result fields after ordered mutation and removal.

        Args:
            source: Original authoritative source marker.
            plan: Original accepted plan.
            preview: Original preview behavior.

        Returns:
            Original presented result.
        """

    def audit(
        self, run: dict[str, object], source: PlaylistTrack, result: FlushResult
    ) -> None:
        """Accept original completion audit before marking an entry complete.

        Args:
            run: Original authoritative run.
            source: Original authoritative source marker.
            result: Original completed outcome.
        """

    def present(
        self,
        action: str,
        source: PlaylistTrack,
        target: CatalogTrack | None,
        preview: bool,
    ) -> None:
        """Present original destination or unfollow text at its accepted boundary.

        Args:
            action: Original action or unfollow presentation.
            source: Original authoritative source marker.
            target: Original optional selected marker.
            preview: Original preview behavior.
        """

    def progress(self, done: int, total: int, message: str) -> None:
        """Present original planning or completed-entry progress.

        Args:
            done: Original completed count.
            total: Original stored entry count.
            message: Original stage text.
        """
