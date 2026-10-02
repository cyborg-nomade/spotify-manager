"""Side effects required by the Slow Listening application workflow."""

from typing import Protocol

from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


class SlowListeningAccess(Protocol):
    """Observe and mutate one playlist, namespace and audit destination."""

    def playlist(self) -> tuple[PlaylistTrack, ...]:
        """Read the live playlist at the original freshness boundary.

        Returns:
            Ordered playable markers with release facts.
        """

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Resolve namespace access and choose persistent state or a preview default.

        Args:
            dry_run: Whether to use a fresh default without reading saved state.

        Returns:
            Validated namespace, retaining its legacy fields.
        """

    def save(self, state: dict[str, object]) -> None:
        """Persist the complete namespace at one checkpoint.

        Args:
            state: Current namespace including choices and execution progress.
        """

    def append(self, target: ReleaseTrack) -> None:
        """Append a replacement before removing its source.

        Args:
            target: Accepted replacement track.
        """

    def remove(self, source: PlaylistTrack) -> None:
        """Remove a source after its replacement is secure.

        Args:
            source: Original playlist marker.
        """

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Append one result, including previews and skips.

        Args:
            run_id: Original run identifier.
            result: Planned or completed transition.
        """


class SlowListeningPresentation(Protocol):
    """Render outcomes without choosing or performing application effects."""

    def skipped(self, source: PlaylistTrack, result: FlushResult) -> None:
        """Show an ineligible source.

        Args:
            source: Original marker.
            result: Skip result and explanation.
        """

    def added(self, target: ReleaseTrack, release_name: str, dry_run: bool) -> None:
        """Show an accepted or previewed replacement.

        Args:
            target: Replacement track.
            release_name: Selected release title, or the legacy unknown marker.
            dry_run: Whether to use preview wording.
        """

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show removal of an advanced source.

        Args:
            source: Original marker.
            dry_run: Whether to use preview wording.
        """

    def completed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show completion of an artist's studio catalog.

        Args:
            source: Final marker.
            dry_run: Whether to use preview wording.
        """

    def resumed(self, source: PlaylistTrack) -> None:
        """Show completion of a plan whose source was already removed.

        Args:
            source: Saved marker absent from the live playlist.
        """
