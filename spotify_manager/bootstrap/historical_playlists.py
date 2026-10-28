"""Compose historical selections and playlist effects with legacy boundaries."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotify_manager.application.historical_playlists import AnniversaryPlaylist
from spotify_manager.application.historical_playlists import BlastPlaylist
from spotify_manager.application.historical_playlists import HistoricalPlaylistEffects
from spotify_manager.application.historical_resolution import HistoricalResolution
from spotify_manager.application.historical_selection import AnniversarySelection
from spotify_manager.application.historical_selection import BlastSelection
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.legacy.historical_inputs import (
    LegacyHistoricalInputs,
)
from spotify_manager.infrastructure.legacy.historical_playlists import (
    LegacyHistoricalPlaylist,
)
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio


def _effects(
    sp: Spotify,
    playlist_id: str,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> HistoricalPlaylistEffects:

    adapter = LegacyHistoricalPlaylist(sp, playlist_id, retry, cancel)
    return HistoricalPlaylistEffects(
        adapter,
        historical_resolution(sp, progress, retry, cancel),
        HistoricalCancellation(cancel),
        OptionalMessages(progress),
    )


def blast_selection(
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
) -> BlastSelection:
    """Construct the invocation dependencies without executing the use case.

    Args:
        path: Local history export.
        today: Optional effective calendar date.
        random: Original random-index source.
        progress: Optional presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    return BlastSelection(
        LegacyHistoricalInputs(path, today, index_reader=random),
        OptionalMessages(progress),
    )


def anniversary_selection(
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> AnniversarySelection:
    """Construct the invocation dependencies without executing the use case.

    Args:
        path: Local history export.
        today: Optional effective local date.
        random: Shared timestamp source.
        progress: Optional presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    return AnniversarySelection(
        LegacyHistoricalInputs(path, today, timestamp_reader=random),
        OptionalMessages(progress),
    )


def blast_playlist(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> BlastPlaylist:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Local history export.
        today: Optional effective local date.
        random: Original random-index reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    selection = blast_selection(path, today, random, progress)
    workflow = BlastPlaylist(
        _effects(sp, playlist_id, progress, retry, cancel), selection
    )
    return workflow


def anniversary_playlist(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> AnniversaryPlaylist:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Destination playlist.
        path: Local history export.
        today: Optional effective local date.
        random: Original random timestamp reader.
        progress: Optional presenter.
        retry: Original retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    selection = anniversary_selection(path, today, random, progress)
    workflow = AnniversaryPlaylist(
        _effects(sp, playlist_id, progress, retry, cancel), selection
    )
    return workflow


def historical_resolution(
    sp: Spotify,
    progress: blast.ProgressCallback | None,
    retry: blast.RetryCall,
    cancel: blast.CancelCheck | None,
) -> HistoricalResolution:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        progress: Optional presenter.
        retry: Existing caller retry policy.
        cancel: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.infrastructure.legacy.historical_playlists import (
        LegacyHistoricalMatches,
    )

    adapter = LegacyHistoricalMatches(sp, retry, cancel)
    workflow = HistoricalResolution(
        adapter,
        HistoricalCancellation(cancel),
        OptionalMessages(progress),
    )
    return workflow


@dataclass(frozen=True)
class HistoricalCancellation:
    """Check the original feature cancellation state.

    Args:
        state: Original optional cancellation resource.
    """

    state: CancellationState | None

    def check(self) -> None:
        """Raise the original feature cancellation error when requested.

        Raises:
            RuntimeError: The feature cancellation state is set.
        """
        from spotify_manager.routines.blast_from_past import check_cancel

        check_cancel(self.state)
