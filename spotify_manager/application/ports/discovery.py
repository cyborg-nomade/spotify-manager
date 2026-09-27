"""Audit and presentation boundaries for artist discovery review decisions."""

from typing import Protocol


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
