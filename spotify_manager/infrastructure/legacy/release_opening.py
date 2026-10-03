"""Bind release startup to original canonical history, state and audit seams."""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.routines import release_check as legacy


def _history_progress(callback: legacy.ProgressCallback, message: str) -> None:
    callback(0, 0, message)


@dataclass
class LegacyReleaseOpening:
    """Keep original configuration and acquire state only after the effective clock.

    Args:
        lastfm: Caller-owned history reader.
        expected_username: Original canonical history ownership.
        state_path: Original state location.
        state_service: Optional original shared service.
        log_path: Original release audit location.
        export_path: Original canonical history location.
        legacy_delta_path: Original optional delta location.
        backup_dir: Original history backup location.
        history_log_path: Original history audit location.
        progress: Original progress observer.
    """

    lastfm: legacy.LastFmReader
    expected_username: str | None
    state_path: Path
    state_service: StateService | None
    log_path: Path
    export_path: Path
    legacy_delta_path: Path | None
    backup_dir: Path
    history_log_path: Path
    progress: legacy.ProgressCallback | None
    state_access: RoutineState = field(init=False)

    def load(self) -> ReleaseState:
        """Acquire and load original state after clock and local-date resolution.

        Returns:
            Original normalized payload, including unknown fields.
        """
        from spotify_manager.routines.release_check import _state_access

        self.state_access = _state_access(self.state_path, self.state_service)
        return self.state_access.load()

    def refresh(self, stamp: datetime) -> ScrobbleHistorySummary:
        """Refresh actual history and forward optional progress.

        Args:
            stamp: Original effective UTC timestamp.

        Returns:
            Original accepted canonical history outcome.
        """
        progress = (
            None if self.progress is None else partial(_history_progress, self.progress)
        )
        from spotify_manager.bootstrap.history import history_refresh

        workflow = history_refresh(
            self.lastfm,
            self.export_path,
            self.legacy_delta_path,
            self.backup_dir,
            self.history_log_path,
            stamp,
            progress,
            None,
        )
        return workflow.run(self.expected_username, False, False)

    def rank(self, history: tuple[Scrobble, ...]) -> tuple[RankedArtist, ...]:
        """Retain the original ranking compatibility seam.

        Args:
            history: Original accepted canonical plays.

        Returns:
            Original ranked eligible artists.
        """
        from spotify_manager.routines.release_check import rank_lastfm_artists

        return rank_lastfm_artists(history)

    def restore(self, active: ReleaseState) -> tuple[RankedArtist, ...]:
        """Retain original frozen-ranking decoding before window validation.

        Args:
            active: Original persisted active run.

        Returns:
            Original frozen ranked artists.
        """
        from spotify_manager.routines.release_check import _active_artists

        return _active_artists(active)

    def persist(self, state: ReleaseState) -> None:
        """Accept the original complete checkpoint and original freshness timestamp.

        Args:
            state: Original mutable new-run state.
        """
        from spotify_manager.routines.release_check import _persist_state

        _persist_state(self.state_access, state)

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Accept original release event bytes after their checkpoint.

        Args:
            run_id: Original durable identity.
            event: Original event name.
            details: Original event fields in insertion order.
        """
        from spotify_manager.routines.release_check import append_event

        append_event(self.log_path, run_id, event, **details)
