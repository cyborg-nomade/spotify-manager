"""Stable values and errors for historical track selection and playlist updates."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Literal

from spotify_manager.domain.history import ScrobbleSelection
from spotify_manager.domain.history_matching import PlaylistState as PlaylistState
from spotify_manager.domain.history_matching import (
    SpotifyTrackMatch as SpotifyTrackMatch,
)


class BlastFromPastError(Exception):
    """Base error for the blast-from-the-past routine."""


class LastFmExportError(BlastFromPastError):
    """Raised when the Last.fm export cannot be read."""


class RandomOrgError(BlastFromPastError):
    """Raised when Random.org cannot provide a valid selection."""


class BlastFromPastConfigError(BlastFromPastError):
    """Raised when the Spotify playlist configuration is invalid."""


class SpotifyTrackResolutionError(BlastFromPastError):
    """Raised when Spotify returns unusable track or playlist data."""


class BlastFromPastCancelledError(BlastFromPastError):
    """Raised when a playlist update is cancelled at a safe boundary."""


@dataclass(frozen=True)
class RandomIndexSet:
    """Unique indexes and the Random.org generation timestamp.

    Args:
        indexes: Date positions in their original response order.
        generated_at: Shared random generation timestamp.
    """

    indexes: tuple[int, ...]
    generated_at: datetime


@dataclass(frozen=True)
class BlastFromPastBatch:
    """A completed batch selected from one Random.org response.

    Args:
        generated_at: Shared random generation timestamp.
        cutoff_date: Inclusive Friday historical cutoff.
        available_dates: Number of eligible populated dates.
        selections: Selected plays in random-index order.
    """

    generated_at: datetime
    cutoff_date: date
    available_dates: int
    selections: tuple[ScrobbleSelection, ...]


@dataclass(frozen=True)
class SpotifySelectionResult:
    """Spotify resolution and playlist outcome for one Last.fm selection.

    Args:
        selection: Original selected play and pagination trace.
        match: Preferred qualified match, if available.
        qualifying_matches: Number of matches after live liked qualification.
        action: Existing membership or pending-addition decision.
    """

    selection: ScrobbleSelection
    match: SpotifyTrackMatch | None
    qualifying_matches: int
    action: Literal["added", "already present", "duplicate selection", "no match"]


@dataclass(frozen=True)
class SpotifySelectionResolution:
    """Resolved Spotify matches and tracks waiting to be added.

    Args:
        results: Per-selection outcomes in their original order.
        pending_matches: Unique additions in first-selection order.
    """

    results: tuple[SpotifySelectionResult, ...]
    pending_matches: tuple[SpotifyTrackMatch, ...]


@dataclass(frozen=True)
class BlastFromPastSpotifySummary:
    """Completed Spotify playlist update for one command invocation.

    Args:
        playlist_id: Destination identifier.
        requested_count: Effective historical date count.
        playlist_length_before: Observed destination size.
        playlist_length_after: Destination size after accepted additions.
        batch: Selected batch, absent when the destination is full.
        results: Per-selection match and membership decisions.
    """

    playlist_id: str
    requested_count: int
    playlist_length_before: int
    playlist_length_after: int
    batch: BlastFromPastBatch | None
    results: tuple[SpotifySelectionResult, ...]

    @property
    def added(self) -> int:
        """Return the original resolved-addition count, including preview decisions.

        Returns:
            Number of results whose action is ``added``.
        """
        return sum(result.action == "added" for result in self.results)


@dataclass(frozen=True)
class DailyMindRadioBatch:
    """Anniversary dates and the scrobbles selected from them.

    Args:
        generated_at: Shared timestamp, absent when no date is populated.
        target_dates: All valid anniversary dates, newest first.
        missing_dates: Targets with missing or empty history buckets.
        selections: Populated targets with their original unfiltered indexes.
    """

    generated_at: datetime | None
    target_dates: tuple[date, ...]
    missing_dates: tuple[date, ...]
    selections: tuple[ScrobbleSelection, ...]


@dataclass(frozen=True)
class DailyMindRadioSpotifySummary:
    """Completed Daily Mind Radio playlist update.

    Args:
        playlist_id: Destination identifier.
        batch: Anniversary dates and selected plays.
        playlist_length_before: Observed size, absent for empty selection.
        playlist_length_after: Projected size, absent for empty selection.
        results: Per-selection resolution outcomes.
    """

    playlist_id: str
    batch: DailyMindRadioBatch
    playlist_length_before: int | None
    playlist_length_after: int | None
    results: tuple[SpotifySelectionResult, ...]

    @property
    def added(self) -> int:
        """Return the original resolved-addition count, including preview decisions.

        Returns:
            Number of results whose action is ``added``.
        """
        return sum(result.action == "added" for result in self.results)
