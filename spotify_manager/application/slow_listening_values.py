"""Public Slow Listening results and workflow errors, retaining legacy aliases."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


type FlushAction = Literal["advance", "complete", "skip"]


class ReleaseOrderReader(Protocol):
    """Own the operator interaction for order releases."""

    async def order_releases(
        self, date: str, releases: tuple[DiscographyRelease, ...], /
    ) -> tuple[str, ...]:
        """Read or report the original operator interaction.

        Args:
            date: Original interaction value.
            releases: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class TrackActionReader(Protocol):
    """Own the operator interaction for choose track."""

    async def choose_track(
        self,
        source: PlaylistTrack,
        target: ReleaseTrack,
        release: DiscographyRelease,
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.
            target: Original interaction value.
            release: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class CompletionNotifier(Protocol):
    """Own the operator interaction for complete."""

    async def complete(self, source: PlaylistTrack, /) -> None:
        """Read or report the original operator interaction.

        Args:
            source: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class SlowListeningError(RuntimeError):
    """Base error for Slow Listening flushes."""


class SlowListeningConfigError(SlowListeningError):
    """Raised when the Slow Listening playlist is not configured."""


class SlowListeningStateError(SlowListeningError):
    """Raised when restart state cannot be read or written safely."""


class SlowListeningCancelledError(SlowListeningError):
    """Raised when interactive release ordering is cancelled."""


@dataclass(frozen=True)
class FlushResult:
    """One planned or completed Slow Listening transition.

    Args:
        source_track: Original marker's display title.
        source_release: Original marker's release title.
        artist: Primary artist's display name.
        action: Original transition classification.
        target_track: Accepted successor title, when present.
        target_release: Selected studio edition title, when present.
        skipped_candidates: Declined candidates encountered while planning.
        reason: Original skip or completion explanation.
        dry_run: Whether this result describes a preview.
    """

    source_track: str
    source_release: str
    artist: str
    action: FlushAction
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: tuple[str, ...] = ()
    reason: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class FlushSummary:
    """Outcome of one Slow Listening invocation.

    Args:
        run_id: Original durable execution identifier.
        total: Number of entries in the saved snapshot.
        processed: Number of results produced by this invocation.
        advanced: Number of advance results.
        completed_artists: Number of completed studio catalogs.
        skipped: Number of ineligible sources.
        paused: Whether the operator quit before finishing the run.
        dry_run: Whether the invocation was a preview.
        resumed: Whether an existing active run was selected.
        results: Results in their original processing order.
    """

    run_id: str
    total: int
    processed: int
    advanced: int
    completed_artists: int
    skipped: int
    paused: bool
    dry_run: bool
    resumed: bool
    results: tuple[FlushResult, ...]
