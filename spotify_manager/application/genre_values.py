"""Genre workflow errors and completed business outcomes."""

from dataclasses import dataclass
from datetime import datetime

from spotify_manager.domain.genres import GenreSource


class GenreRevealStateError(RuntimeError):
    """Raised when genre-reveal state cannot be read or written."""


class GenreRevealSourceError(RuntimeError):
    """Raised when an Every Noise or Spotify public page cannot be resolved."""


class GenreRevealConfigError(RuntimeError):
    """Raised when the destination playlist is not configured."""


class GenreRevealLogError(RuntimeError):
    """Raised when a completed operation cannot be recorded."""


class GenreRevealCompleteError(RuntimeError):
    """Raised when the nearest-neighbour route has no incomplete genres."""


@dataclass(frozen=True)
class GenreOutcome:
    """Original completed source/save/copy outcome before boundary presentation.

    Args:
        source: Original public source metadata.
        destination_playlist_id: Original target identity.
        source_track_uris: Original source marker order.
        added_track_uris: Original accepted marker order.
        already_present_track_uris: Original destination overlap in source order.
        completed_at: Original completion clock after accepted Spotify writes.
    """

    source: GenreSource
    destination_playlist_id: str
    source_track_uris: tuple[str, ...]
    added_track_uris: tuple[str, ...]
    already_present_track_uris: tuple[str, ...]
    completed_at: datetime
