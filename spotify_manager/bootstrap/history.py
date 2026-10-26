"""Compose canonical history refresh with its existing external boundaries."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryReader
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.routines import scrobble_history as legacy


def _checked_at(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def history_refresh(
    lastfm: legacy.LastFmReader,
    export_path: Path,
    legacy_delta_path: Path | None,
    backup_dir: Path,
    log_path: Path,
    now: datetime | None,
    progress_callback: legacy.ProgressCallback | None,
    cancel_check: legacy.CancelCheck | None,
) -> HistoryRefresh:
    """Construct the invocation dependencies without executing the use case.

    Args:
        lastfm: Existing Last.fm client.
        export_path: Canonical history file.
        legacy_delta_path: Optional legacy delta.
        backup_dir: Original backup destination.
        log_path: Original audit destination.
        now: Optional effective refresh time.
        progress_callback: Optional presentation callback.
        cancel_check: Optional cancellation predicate.

    Returns:
        The configured application dependencies or workflow.
    """
    storage = LegacyHistoryStorage(export_path, legacy_delta_path, backup_dir, log_path)
    workflow = HistoryRefresh(
        storage,
        LegacyHistoryReader(lastfm),
        CheckedAtClock(now),
        HistoryCancellation(cancel_check),
        OptionalMessages(progress_callback),
    )
    return workflow


@dataclass(frozen=True)
class CheckedAtClock:
    """Retain the optional effective calendar value.

    Args:
        override: Original caller-selected date or instant.
    """

    override: datetime | None

    def now(self) -> datetime:
        """Observe the original effective date at its existing boundary.

        Returns:
            Original normalized date or instant.
        """
        return _checked_at(self.override)


@dataclass(frozen=True)
class HistoryCancellation:
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
        from spotify_manager.routines.scrobble_history import check_cancel

        check_cancel(self.state)
