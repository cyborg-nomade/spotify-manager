"""Review saved albums through explicit library and interaction contracts."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum


type ReviewOutcome = Literal[
    "previously kept", "keep", "auto-removed", "quit", "kept anyway", "skip", "removed"
]


@dataclass
class ReviewCounts:
    """Completed outcomes in the current invocation.

    Args:
        kept: Previously kept, automatically kept, and explicitly kept albums.
        skipped: Albums explicitly skipped during this invocation.
        removed: Successful automatic and manual removals.
        followed: Artists followed before evaluating their albums.
    """

    kept: int = 0
    skipped: int = 0
    removed: int = 0
    followed: int = 0


class AlbumReviewLibrary(Protocol):
    """Library observations and effects needed by one album-review run."""

    def albums(self) -> list[YourLibraryAlbum]:
        """Load the original ordered review input and its related state.

        Returns:
            Albums including any duplicate observations.
        """

    def previously_kept(self, album: YourLibraryAlbum) -> bool:
        """Read an explicit persisted keep decision.

        Args:
            album: Current review item.

        Returns:
            Whether a prior user choice bypasses this review.
        """

    def follow_artist(self, album: YourLibraryAlbum) -> bool:
        """Resolve, follow, and persist the album artist when necessary.

        Args:
            album: Current review item.

        Returns:
            Whether a new follow completed.
        """

    def evaluate(self, album: YourLibraryAlbum) -> AlbumEvaluation:
        """Read track facts and assess the configured retention threshold.

        Args:
            album: Current review item.

        Returns:
            The assessment and its original source metadata.
        """

    def live_likes(self, album: YourLibraryAlbum, track_ids: list[str]) -> int:
        """Read current membership before offering removal.

        Args:
            album: Item used in retry descriptions.
            track_ids: Ordered known track identifiers.

        Returns:
            Count of truthy membership observations.
        """

    def remove(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
        *,
        automatic: bool,
    ) -> None:
        """Delete, update the mirror, and audit in the original order.

        Args:
            album: Current review item.
            evaluation: Assessment recorded in the audit.
            live_likes: Last live membership count, when available.
            automatic: Whether zero live likes triggered removal.
        """

    def keep(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
    ) -> None:
        """Persist an explicit keep choice.

        Args:
            album: Current review item.
            evaluation: Assessment recorded with the choice.
            live_likes: Last live membership count, when available.
        """


class AlbumReviewInteraction(Protocol):
    """Presentation and user choices, owned by the invoking interface."""

    def outcome(
        self,
        outcome: ReviewOutcome,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation | None,
        position: int,
        total: int,
    ) -> None:
        """Present an outcome without changing library state.

        Args:
            outcome: Completed decision or the user's request to stop.
            album: Current review item.
            evaluation: Assessment, absent for previously kept albums.
            position: One-based review position.
            total: Original number of albums.
        """

    def candidate(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        position: int,
        total: int,
    ) -> None:
        """Present the candidate before reading live membership.

        Args:
            album: Current review item.
            evaluation: Assessment and source metadata.
            position: One-based review position.
            total: Original number of albums.
        """

    def show_live_likes(self, count: int | None) -> None:
        """Present the live count or unavailable-membership message.

        Args:
            count: Live count, or None when no identifiers are known.
        """

    def choose(self, album: YourLibraryAlbum, evaluation: AlbumEvaluation) -> str:
        """Read a normalized action, retaining detail and invalid-input prompts.

        Args:
            album: Current review item.
            evaluation: Assessment shown with the prompt.

        Returns:
            The original remove, keep, skip, or quit action.
        """

    def progress(self, position: int, total: int) -> None:
        """Deliver progress at the original completion boundary.

        Args:
            position: Completed review position.
            total: Original number of albums.
        """

    def finish(self, counts: ReviewCounts) -> None:
        """Present the final counts, including after a normal quit.

        Args:
            counts: Outcomes completed before exit.
        """


def _live_likes(
    library: AlbumReviewLibrary, album: YourLibraryAlbum, evaluation: AlbumEvaluation
) -> int | None:
    track_ids = []
    for track in evaluation.tracks:
        if track.spotify_id:
            track_ids.append(track.spotify_id)
    if not track_ids:
        return None
    return library.live_likes(album, track_ids)


def _review_candidate(
    library: AlbumReviewLibrary,
    interaction: AlbumReviewInteraction,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
) -> ReviewOutcome:
    live_likes = _live_likes(library, album, evaluation)
    if live_likes == 0:
        library.remove(album, evaluation, live_likes, automatic=True)
        return "auto-removed"
    interaction.show_live_likes(live_likes)
    action = interaction.choose(album, evaluation)
    if action == "quit":
        return "quit"
    if action == "keep":
        library.keep(album, evaluation, live_likes)
        return "kept anyway"
    if action == "skip":
        return "skip"
    library.remove(album, evaluation, live_likes, automatic=False)
    return "removed"


def _review_one(
    library: AlbumReviewLibrary,
    interaction: AlbumReviewInteraction,
    album: YourLibraryAlbum,
    counts: ReviewCounts,
    position: int,
    total: int,
) -> ReviewOutcome:
    if library.previously_kept(album):
        interaction.outcome("previously kept", album, None, position, total)
        return "previously kept"
    counts.followed += int(library.follow_artist(album))
    evaluation = library.evaluate(album)
    if evaluation.decision == "keep":
        interaction.outcome("keep", album, evaluation, position, total)
        return "keep"
    interaction.candidate(album, evaluation, position, total)
    outcome = _review_candidate(library, interaction, album, evaluation)
    interaction.outcome(outcome, album, evaluation, position, total)
    return outcome


def _count_outcome(counts: ReviewCounts, outcome: ReviewOutcome) -> None:
    if outcome in {"previously kept", "keep", "kept anyway"}:
        counts.kept += 1
    elif outcome in {"auto-removed", "removed"}:
        counts.removed += 1
    else:
        counts.skipped += 1


def review_albums(
    library: AlbumReviewLibrary, interaction: AlbumReviewInteraction
) -> None:
    """Review each album while preserving prompt and completion boundaries.

    Args:
        library: Run-scoped observations and ordered library effects.
        interaction: Presentation, actions, and cancellation-aware progress.

    Raises:
        RuntimeError: An integration or caller interrupts the review.
    """
    albums = library.albums()
    counts = ReviewCounts()
    for position, album in enumerate(albums, start=1):
        outcome = _review_one(
            library, interaction, album, counts, position, len(albums)
        )
        if outcome == "quit":
            break
        _count_outcome(counts, outcome)
        interaction.progress(position, len(albums))
    interaction.finish(counts)
