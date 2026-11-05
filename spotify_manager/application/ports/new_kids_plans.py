"""Typed operator boundary for the four-release New Kids plan editor."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.discovery import RankedRelease


@dataclass(frozen=True)
class ReleasePlanDraft:
    """Present a complete discography without preselecting the queue album.

    Args:
        artist: Logical artist display name.
        releases: Complete canonical catalogue, including optional categories.
        queue_album: Album currently represented in Queue 2, for context only.
        notice: Recoverable selection or availability feedback.
    """

    artist: str
    releases: tuple[RankedRelease, ...]
    queue_album: str
    notice: str = ""


@dataclass(frozen=True)
class ReleasePlanSubmission:
    """An ordered plan or explicit transfer control decision.

    Args:
        action: Accept, skip this artist's transfer, or stop the invocation.
        release_ids: Exact IDs in listening order.
        confirm_short: Explicit acknowledgement of a shorter plan.
    """

    action: Literal["select", "skip", "quit"]
    release_ids: tuple[str, ...] = ()
    confirm_short: bool = False


class ReleasePlanReader(Protocol):
    """Read a plan using a web or terminal interaction owned by the invocation."""

    async def choose_plan(self, draft: ReleasePlanDraft) -> ReleasePlanSubmission:
        """Show the ordered editor and read one complete decision.

        Args:
            draft: Current complete catalogue and selection feedback.

        Returns:
            Ordered selection, explicit shorter confirmation, skip or quit.
        """
