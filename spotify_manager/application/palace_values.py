"""Stable Palace errors, live-refresh facts and complete compatibility outcomes."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.models.your_library import YourLibraryAlbum


class PalaceOfMemoryError(RuntimeError):
    """Base error for Palace of Memory runs."""


class PalaceOfMemoryConfigError(PalaceOfMemoryError):
    """Raised when the playlist setting is missing or invalid."""


class PalaceOfMemoryDataError(PalaceOfMemoryError):
    """Raised when a local mirror or Spotify response is unusable."""


class PalaceOfMemoryStateError(PalaceOfMemoryError):
    """Raised when the alphabetical cursor cannot be read or persisted."""


@dataclass(frozen=True)
class SavedAlbumRefresh:
    """Result of rebuilding the canonical saved-album mirror.

    Args:
        checked_at: Original live-refresh timestamp.
        previous: Previous usable mirror size.
        current: Refreshed canonical mirror size.
        added: New live album identities.
        removed: Album identities absent from the refreshed live mirror.
        skipped: Original unusable raw row count.
        persisted: Whether the mirror was replaced.
        backup_path: Original backup location when replaced, if any.
    """

    checked_at: datetime
    previous: int
    current: int
    added: int
    removed: int
    skipped: int
    persisted: bool
    backup_path: str | None


@dataclass(frozen=True)
class AlphabeticalCursorUpdate:
    """A manually persisted next position in the saved-album ordering.

    Args:
        next_index: Original zero-based next alphabetical position.
        next_album: Original complete saved-album model at the next position.
        album_refresh: Original live preflight refresh outcome.
    """

    next_index: int
    next_album: YourLibraryAlbum
    album_refresh: SavedAlbumRefresh


@dataclass(frozen=True)
class PalaceOfMemorySummary:
    """Completed Palace of Memory planning or mutation.

    Args:
        generated_at: Original Random.org selection timestamp.
        playlist_id: Original destination identity.
        dry_run: Original preview behavior.
        cutoff_date: Original latest eligible historical date.
        available_dates: Original count of eligible album-bearing dates.
        alphabetical_start_index: Original zero-based selected starting position.
        alphabetical_next_index: Original zero-based next position after selection.
        alphabetical_cursor_overridden: Whether the caller supplied a manual start.
        playlist_length_before: Original final live destination size.
        playlist_length_after: Original projected size after distinct pending markers.
        album_refresh: Original live preflight refresh outcome.
        results: Original ordered alphabetical and historical outcomes.
    """

    generated_at: datetime
    playlist_id: str
    dry_run: bool
    cutoff_date: date
    available_dates: int
    alphabetical_start_index: int
    alphabetical_next_index: int
    alphabetical_cursor_overridden: bool
    playlist_length_before: int
    playlist_length_after: int
    album_refresh: SavedAlbumRefresh
    results: tuple[PalaceAlbumResult, ...]

    @property
    def added(self) -> int:
        """Return the number of first tracks added or projected.

        Returns:
            Original distinct pending marker count.
        """
        return sum(result.action == "added" for result in self.results)
