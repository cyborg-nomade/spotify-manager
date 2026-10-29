"""Compose dormant history and catalog policies with original clocks and effects."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotify_manager.application.dormant_recovery import DormantRecovery
from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import OptionalReviewProgress
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.legacy.dormant_artists import LegacyDormantRecovery
from spotify_manager.infrastructure.legacy.dormant_tracks import LegacyDormantCatalog
from spotify_manager.routines import blast_from_past_artists as legacy


def _clock(today: date | None) -> date:
    return today or legacy.datetime.now(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()


def dormant_tracks(sp: Spotify, retry: legacy.RetryCall) -> DormantLikedTrack:
    """Construct original dormant-track resources without executing selection.

    Args:
        sp: Caller-owned synchronous Spotify client.
        retry: Original retry and cancellation boundary.

    Returns:
        Named liked-track application stage.
    """
    return DormantLikedTrack(LegacyDormantCatalog(sp, retry))


def dormant_recovery(
    sp: Spotify,
    playlist_id: str,
    path: Path,
    today: date | None,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall,
    cancel: legacy.CancelCheck | None,
) -> DormantRecovery:
    """Construct the invocation dependencies without executing the use case.

    Args:
        sp: Caller-owned Spotify client.
        playlist_id: Original destination.
        path: Original canonical history.
        today: Optional effective date.
        echo: Original skip presentation.
        progress: Original progress observer.
        retry: Original retry policy.
        cancel: Original cancellation callback.

    Returns:
        The configured application dependencies or workflow.
    """
    effects = LegacyDormantRecovery(sp, playlist_id, path, retry, cancel)
    workflow = DormantRecovery(
        effects,
        dormant_tracks(sp, retry),
        DormantDate(today),
        DormantCancellation(cancel),
        OptionalReviewProgress(progress),
        echo,
        legacy.LOOKBACK_YEARS,
    )
    return workflow


@dataclass(frozen=True)
class DormantDate:
    """Retain the optional effective calendar value.

    Args:
        override: Original caller-selected date or instant.
    """

    override: date | None

    def today(self) -> date:
        """Observe the original effective date at its existing boundary.

        Returns:
            Original normalized date or instant.
        """
        return _clock(self.override)


@dataclass(frozen=True)
class DormantCancellation:
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
