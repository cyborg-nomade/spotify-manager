"""Discography application errors and original complete execution result."""

from dataclasses import dataclass

from spotify_manager.domain.discography_values import QueueName


class DiscographyError(RuntimeError):
    """Base error for discography planning and queue updates."""


class DiscographyConfigError(DiscographyError):
    """Raised when one of the three source playlists is not configured."""


class DiscographyStateError(DiscographyError):
    """Raised when discography state or logs cannot be persisted safely."""


class DiscographyCancelledError(DiscographyError):
    """Raised when release selection is cancelled."""


@dataclass(frozen=True)
class DiscographyRunSummary:
    """Outcome of applying a confirmed discography plan.

    Args:
        removed_artists: Original completed artist count.
        removed_markers: Original successful unique batch removal count.
        next_queue: Original final priority.
    """

    removed_artists: int
    removed_markers: int
    next_queue: QueueName
