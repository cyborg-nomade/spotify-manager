"""Typed operator and catalog resources for editable discography release drafts."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.discography_links import ReviewRelease
from spotify_manager.domain.discography_values import QueueArtist


type ReleaseReviewAction = Literal["add", "select", "none", "quit"]


@dataclass(frozen=True)
class ReleaseReviewDraft:
    """An artist's current options and unconfirmed checklist.

    Args:
        artist: Stable queue artist being reviewed.
        entries: Fetched and explicitly linked editions in chronology order.
        selected_ids: Current checked identities, retained across link additions.
        remaining: Available weekly slots, or None for the first artist.
        notices: Per-reference outcomes from the most recent addition.
    """

    artist: QueueArtist
    entries: tuple[ReviewRelease, ...]
    selected_ids: tuple[str, ...]
    remaining: int | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseReviewSubmission:
    """One explicit edit or final artist-checklist decision.

    Args:
        choice: Add links, accept selected identities, decline or cancel.
        release_ids: Checked identities at submission time.
        references: Album links/URIs to resolve when adding.
    """

    choice: ReleaseReviewAction
    release_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


class DiscographyAlbumAccess(Protocol):
    """Resolve one exact album identity without applying automatic artist filters."""

    async def album(self, identity: str) -> ReviewRelease:
        """Read checked metadata, availability and saved status for an album.

        Args:
            identity: Validated Spotify album identifier.

        Returns:
            Explicit edition and its actual display credits.

        Raises:
            DiscographyAlbumError: The album is unavailable or its metadata invalid.
        """
        ...


class DiscographyReviewReader(Protocol):
    """Present a draft and observe the owning invocation's cancellation."""

    async def review_releases(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        """Read one edit or artist-checklist decision.

        Args:
            draft: Current complete options, selections and feedback.

        Returns:
            Explicit submitted action and its selected identities/references.
        """
        ...

    def check(self) -> None:
        """Stop if the owning interface reports cancellation.

        Raises:
            RuntimeError: The owning invocation has been cancelled.
        """
        ...
