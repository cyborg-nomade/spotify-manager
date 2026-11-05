"""Typed operator boundary for the four-release New Kids plan editor."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.discovery import RankedRelease


@dataclass(frozen=True)
class ReleasePlanDraft:
    """Present a complete discography for a transfer or existing-artist migration.

    Args:
        artist: Logical artist display name.
        releases: Complete canonical catalogue, including optional categories.
        queue_album: Source album context; automatically included only for migration.
        notice: Recoverable selection or availability feedback.
        migration: Whether this edits a plan for an existing playlist marker.
        current_release_id: Confidently identified current edition, locked when known.
        current_track: Current playlist track retained during migration.
        selected_ids: Initial or corrected selection in listening order.
    """

    artist: str
    releases: tuple[RankedRelease, ...]
    queue_album: str
    notice: str = ""
    migration: bool = False
    current_release_id: str | None = None
    current_track: str | None = None
    selected_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleasePlanSubmission:
    """An ordered plan or explicit artist skip/quit decision.

    Args:
        action: Accept, defer this artist for the invocation, or stop.
        release_ids: Exact IDs in listening order.
        confirm_short: Explicit acknowledgement of a shorter plan.
        current_release_id: Explicit current edition when resolving migration.
        confirm_current: Acknowledgement of that current-edition resolution.
    """

    action: Literal["select", "skip", "quit"]
    release_ids: tuple[str, ...] = ()
    confirm_short: bool = False
    current_release_id: str | None = None
    confirm_current: bool = False


class ReleasePlanReader(Protocol):
    """Read a plan using a web or terminal interaction owned by the invocation."""

    async def choose_plan(self, draft: ReleasePlanDraft) -> ReleasePlanSubmission:
        """Show the ordered editor and read one complete decision.

        Args:
            draft: Current complete catalogue and selection feedback.

        Returns:
            Ordered selection, explicit shorter confirmation, skip or quit.
        """
