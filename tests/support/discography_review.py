"""Independent editable checklists and exact album observations for link review."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

from spotify_manager.application.ports.discography_review import ReleaseReviewDraft
from spotify_manager.application.ports.discography_review import ReleaseReviewSubmission
from spotify_manager.domain.discography_links import ReviewRelease
from tests.support.discography_run import release


FIRST = "a" * 22
SECOND = "b" * 22
THIRD = "c" * 22


def linked(
    identity: str, name: str = "Linked record", date: str = "2021"
) -> ReviewRelease:
    """Build an exact, explicitly added edition independent of parsers.

    Args:
        identity: Exact Spotify album ID.
        name: Human-readable edition title.
        date: Edition's own chronological date.

    Returns:
        Complete unchecked catalog facts and actual credits.
    """
    record = replace(
        release(identity, False), name=name, release_date=date, chronology_date=date
    )
    return ReviewRelease(record, ("Other Artist", "Guest Artist"), True)


@dataclass
class ReviewMemory:
    """Record complete drafts and exact album reads without effects or file I/O.

    Args:
        answers: Scripted actions; exhausted scripts accept current checked IDs.
        albums: Exact metadata or explicitly scripted external failures.
        drafts: Complete operator-visible draft observations.
        requested: Album identities actually read.
        checks: Cancellation observations so far.
        interrupt_at: Optional cancellation boundary to interrupt.
    """

    answers: list[ReleaseReviewSubmission] = field(default_factory=list)
    albums: dict[str, ReviewRelease | RuntimeError] = field(default_factory=dict)
    drafts: list[ReleaseReviewDraft] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    checks: int = 0
    interrupt_at: int | None = None

    async def album(self, identity: str) -> ReviewRelease:
        """Observe one exact album lookup or raise its scripted failure.

        Args:
            identity: Parsed Spotify album ID.

        Returns:
            Exact scripted edition facts.

        Raises:
            RuntimeError: The scripted external failure occurs.
        """
        self.requested.append(identity)
        result = self.albums[identity]
        if isinstance(result, RuntimeError):
            raise result
        return result

    async def review_releases(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        """Record a complete draft and return one explicit decision.

        Args:
            draft: Offered options, checked IDs and per-reference outcomes.

        Returns:
            Scripted response or acceptance of current checked IDs.
        """
        self.drafts.append(draft)
        if self.answers:
            return self.answers.pop(0)
        return ReleaseReviewSubmission("select", draft.selected_ids)

    def check(self) -> None:
        """Interrupt the selected read-only cancellation boundary.

        Raises:
            RuntimeError: The owning invocation was cancelled.
        """
        self.checks += 1
        if self.checks == self.interrupt_at:
            raise RuntimeError("review cancelled")
