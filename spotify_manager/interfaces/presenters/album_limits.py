"""Original album-review messages and action prompts for CLI and HTTP callers."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.album_limits import ReviewCounts
from spotify_manager.application.album_limits import ReviewOutcome
from spotify_manager.application.artist_follows import ArtistFollowOutcome
from spotify_manager.application.ports.runtime import CountProgress
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum


type ProgressCallback = CountProgress


type Echo = Messages


class ActionReader(Protocol):
    """Own the operator interaction for choose action."""

    async def choose_action(
        self, album: YourLibraryAlbum, evaluation: AlbumEvaluation, /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            album: Original interaction value.
            evaluation: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


def present_artist_follow(
    outcome: ArtistFollowOutcome, album: YourLibraryAlbum, echo: Echo
) -> None:
    """Present artist-follow effects after their original completion boundary.

    Args:
        outcome: Completed application decision.
        album: Original unresolved-artist fallback label.
        echo: Existing output callback.
    """
    if outcome.action == "unresolved":
        echo.echo(f"Could not resolve artist id for: {album.artist}")
        return
    if outcome.action != "followed":
        return
    assert outcome.artist is not None and outcome.persistence is not None
    echo.echo(f"Followed artist: {outcome.artist.name}")
    if outcome.persistence.total_artists_updated:
        echo.echo(f"Recorded artist in artists_total.json: {outcome.artist.name}")
    if outcome.persistence.stats_history_updated:
        echo.echo("Updated stats_history.json.")


def format_album_label(album: YourLibraryAlbum) -> str:
    """Format a compact album label.

    Args:
        album: Library item being presented.

    Returns:
        Original album and artist label.
    """
    return f"{album.album} - {album.artist}"


def format_evaluation_summary(evaluation: AlbumEvaluation) -> str:
    """Format the liked-track threshold and assessment.

    Args:
        evaluation: Album observations and threshold.

    Returns:
        Original human-readable assessment.
    """
    liked_pct = evaluation.liked_ratio * 100
    threshold_pct = evaluation.threshold * 100
    return (
        f"Liked: {evaluation.liked_tracks} / {evaluation.total_tracks} "
        f"({liked_pct:.1f}%, threshold {threshold_pct:.1f}%, "
        f"required {evaluation.required_liked_tracks})"
    )


def echo_track_details(evaluation: AlbumEvaluation, echo: Echo) -> None:
    """Present track-level membership in its observed order.

    Args:
        evaluation: Album containing the track observations.
        echo: Output sink owned by the interface.
    """
    for index, track in enumerate(evaluation.tracks, start=1):
        marker = "liked" if track.liked else "not liked"
        echo.echo(f"  {index:02d}. [{marker}] {track.name}")


def _normalized_action(action: str, evaluation: AlbumEvaluation) -> str | None:
    if action in {"r", "remove"} or (not action and evaluation.decision == "remove"):
        return "remove"
    if action in {"k", "keep"}:
        return "keep"
    if action in {"s", "skip", ""}:
        return "skip"
    if action in {"q", "quit"}:
        return "quit"
    return None


async def read_action(
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    action_reader: ActionReader,
    echo: Echo,
) -> str:
    """Read a choice, retaining detail requests and invalid-input retries.

    Args:
        album: Current library item.
        evaluation: Assessment shown to the user.
        action_reader: Interface callback reading a choice.
        echo: Interface output sink.

    Returns:
        Normalized remove, keep, skip, or quit action.
    """
    while True:
        action = (
            (await action_reader.choose_action(album, evaluation)).strip().casefold()
        )
        normalized = _normalized_action(action, evaluation)
        if normalized is not None:
            return normalized
        if action in {"d", "details"}:
            echo_track_details(evaluation, echo)
            continue
        echo.echo("Choose r/remove, k/keep, s/skip, d/details, or q/quit.")


def _outcome_message(
    outcome: ReviewOutcome,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation | None,
    position: int,
    total: int,
) -> str:
    label = format_album_label(album)
    if outcome == "previously kept":
        return f"[{position}/{total}] previously kept: {label}"
    if outcome == "keep":
        assert evaluation is not None
        summary = format_evaluation_summary(evaluation)
        return f"[{position}/{total}] keep: {label} - {summary}"
    if outcome == "quit":
        return "Stopping review."
    prefixes = {
        "auto-removed": "Auto-removed (0 live liked tracks)",
        "kept anyway": "Kept anyway",
        "skip": "Skipped",
        "removed": "Removed",
    }
    return f"{prefixes[outcome]}: {label}"


@dataclass(frozen=True)
class AlbumReviewPresenter:
    """Bind the existing interaction callbacks to album-review presentation.

    Args:
        action_reader: Original interface choice callback.
        output: Output sink.
        progress_callback: Optional progress and cancellation callback.
    """

    action_reader: ActionReader
    output: Echo
    progress_callback: ProgressCallback | None

    def outcome(
        self,
        outcome: ReviewOutcome,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation | None,
        position: int,
        total: int,
    ) -> None:
        """Present one outcome.

        Args:
            outcome: Completed decision or quit request.
            album: Current item.
            evaluation: Assessment when available.
            position: One-based position.
            total: Original album count.
        """
        self.output.echo(_outcome_message(outcome, album, evaluation, position, total))

    def candidate(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        position: int,
        total: int,
    ) -> None:
        """Show the removal candidate before its live membership check.

        Args:
            album: Current item.
            evaluation: Assessment and source metadata.
            position: One-based position.
            total: Original album count.
        """
        self.output.echo("")
        self.output.echo(
            f"[{position}/{total}] remove candidate: {format_album_label(album)}"
        )
        self.output.echo(format_evaluation_summary(evaluation))
        self.output.echo(f"Source: {evaluation.source}")

    def show_live_likes(self, count: int | None) -> None:
        """Present live membership availability.

        Args:
            count: Current count or None when identifiers are unavailable.
        """
        if count is None:
            self.output.echo("Live liked tracks: unavailable; asking for confirmation.")
            return
        self.output.echo(f"Live liked tracks: {count}")

    async def choose(self, album: YourLibraryAlbum, evaluation: AlbumEvaluation) -> str:
        """Read the original interface action.

        Args:
            album: Current item.
            evaluation: Assessment shown with the prompt.

        Returns:
            Normalized action.
        """
        return await read_action(album, evaluation, self.action_reader, self.output)

    def progress(self, position: int, total: int) -> None:
        """Deliver completion progress when a callback exists.

        Args:
            position: Completed position.
            total: Original album count.
        """
        if self.progress_callback is not None:
            self.progress_callback.progress(position, total)

    def finish(self, counts: ReviewCounts) -> None:
        """Present final review counts.

        Args:
            counts: Completed outcomes.
        """
        self.output.echo("")
        self.output.echo(
            f"Review complete. Kept: {counts.kept}. Skipped: {counts.skipped}. "
            f"Removed: {counts.removed}. Followed artists: {counts.followed}."
        )
