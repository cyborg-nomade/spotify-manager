"""Audit and presentation boundaries for artist discovery review decisions."""

from typing import Protocol

from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation


class DiscoveryAudit(Protocol):
    """Append original named discovery events, including preview observations."""

    def event(self, name: str, **details: object) -> None:
        """Append one event at the application-selected boundary.

        Args:
            name: Existing audit event identifier.
            details: Original structured event fields, retaining their order.
        """


class DiscoveryPlanningPresentation(Protocol):
    """Render current-year completion observations before their audit event."""

    def release_progress(self, artist: str, completed: int, year: int) -> None:
        """Show the original historical completion count.

        Args:
            artist: Logical artist display name.
            completed: Number of catalog entries considered completed this year.
            year: Existing invocation year.
        """


class DiscoveryLibrary(Protocol):
    """External effects required when a discovery release reaches its boundary."""

    def saved(self, release: RankedRelease) -> bool:
        """Read tolerant live saved membership.

        Args:
            release: Completed release.

        Returns:
            Whether the first returned status is truthy.
        """

    def save_album(self, release: RankedRelease) -> None:
        """Save one release remotely.

        Args:
            release: Release accepted by the keep rule.
        """

    def remove_album(self, release: RankedRelease) -> None:
        """Unsave one release remotely.

        Args:
            release: Release rejected by the keep rule.
        """

    def removed_audit(
        self, release: RankedRelease, evaluation: AlbumEvaluation
    ) -> None:
        """Append recovery information after removal and before mirror changes.

        Args:
            release: Release just removed remotely.
            evaluation: Accepted live removal decision.
        """

    def mirror(self, release: RankedRelease, should_save: bool) -> None:
        """Reconcile the local mirror, including unchanged remote memberships.

        Args:
            release: Completed release.
            should_save: Desired membership according to the live evaluation.
        """


class DiscoveryLibraryPresentation(Protocol):
    """Render reconciliation after its routine audit succeeds."""

    def reconciled(
        self,
        release: RankedRelease,
        evaluation: AlbumEvaluation,
        action: str,
        dry_run: bool,
    ) -> None:
        """Show the original reconciliation outcome.

        Args:
            release: Completed release.
            evaluation: Accepted live decision and track counts.
            action: Original persisted or preview action string.
            dry_run: Whether to use preview wording.
        """
