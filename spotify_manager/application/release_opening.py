"""Open or resume the original release-check window before destination observations."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol
from typing import cast

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.release_check_values import ReleaseCheckError
from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import RankedArtist


type ReleaseState = dict[str, object]


class ReleaseOpeningEffects(Protocol):
    """Original history, state, frozen ranking and accepted-start audit boundaries."""

    def load(self) -> ReleaseState:
        """Load original state after resolving the effective clock and local date.

        Returns:
            Original normalized payload, including unknown fields.
        """

    def refresh(self, stamp: datetime) -> ScrobbleHistorySummary:
        """Perform original actual history refresh even during a release preview.

        Args:
            stamp: Original effective UTC timestamp.

        Returns:
            Original accepted history outcome.
        """

    def rank(self, history: tuple[Scrobble, ...]) -> tuple[RankedArtist, ...]:
        """Apply original artist ranking after the history refresh.

        Args:
            history: Original canonical plays.

        Returns:
            Original ranked eligible artists.
        """

    def restore(self, active: ReleaseState) -> tuple[RankedArtist, ...]:
        """Restore original frozen ranking before validating the active window.

        Args:
            active: Original persisted active run.

        Returns:
            Original frozen ranked artists.
        """

    def persist(self, state: ReleaseState) -> None:
        """Accept the original initial checkpoint before its started audit.

        Args:
            state: Original complete new-run state.
        """

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Accept the original started event after the initial checkpoint.

        Args:
            run_id: Original durable run identity.
            event: Original event name.
            details: Original event fields in insertion order.
        """


@dataclass(frozen=True)
class OpenedReleaseRun:
    """Original opening observations retained for the remaining release-check stages.

    Args:
        generated_at: Effective original UTC timestamp.
        today: Effective original local date.
        persisted_state: Original loaded state used for preview learning.
        state: Original deep-copied working state.
        active: Original active run, new or resumed.
        artists: Original new or frozen ranked artists.
        checked_from: Original inclusive window start.
        checked_through: Original inclusive window end.
        run_id: Original durable run identity.
        resumed: Whether an original active run was present.
        history_refresh: Original refresh outcome, absent on resumed runs.
    """

    generated_at: datetime
    today: date
    persisted_state: ReleaseState
    state: ReleaseState
    active: ReleaseState
    artists: tuple[RankedArtist, ...]
    checked_from: date
    checked_through: date
    run_id: str
    resumed: bool
    history_refresh: ScrobbleHistorySummary | None


def _window_start(raw_previous: object, today: date) -> date:
    start_of_year = date(today.year, 1, 1)
    if not isinstance(raw_previous, str):
        return start_of_year
    try:
        previous = date.fromisoformat(raw_previous)
    except ValueError as exc:
        raise ReleaseCheckStateError(
            "The previous release-check date is invalid."
        ) from exc
    return min(previous, start_of_year)


def _active_window(active: ReleaseState) -> tuple[date, date, str]:
    try:
        return (
            date.fromisoformat(str(active["checked_from"])),
            date.fromisoformat(str(active["checked_through"])),
            str(active["run_id"]),
        )
    except (KeyError, ValueError) as exc:
        raise ReleaseCheckStateError(
            "The active release-check window is invalid."
        ) from exc


def _active_record(
    run_id: str,
    stamp: datetime,
    start: date,
    today: date,
    artists: tuple[RankedArtist, ...],
) -> ReleaseState:
    return {
        "run_id": run_id,
        "started_at": stamp.isoformat(),
        "checked_from": start.isoformat(),
        "checked_through": today.isoformat(),
        "artists": [asdict(artist) for artist in artists],
        "completed_artist_keys": [],
        "pending_release_id": None,
    }


@dataclass(frozen=True)
class ReleaseRunOpening:
    """Preserve original resume authority and preview refresh/checkpoint semantics.

    Args:
        effects: Original history, durable state and accepted-start boundaries.
        clock: Original effective UTC clock.
        local_date: Original local calendar conversion.
        run_id: Original sortable run identifier.
        minimum_scrobbles: Original threshold included in the empty-ranking error.
    """

    effects: ReleaseOpeningEffects
    clock: Callable[[], datetime]
    local_date: Callable[[datetime], date]
    run_id: Callable[[datetime], str]
    minimum_scrobbles: int = 100

    def run(self, dry_run: bool) -> OpenedReleaseRun:
        """Load original state, resume its window or refresh history before a new start.

        Args:
            dry_run: Original release-preview mode, retaining actual history refresh.

        Returns:
            Original opening observations after any accepted checkpoint and audit.

        Raises:
            ReleaseCheckError: Original history has no sufficiently listened artists.
            ReleaseCheckStateError: Original window or frozen ranking is unusable.
        """
        stamp = self.clock()
        today = self.local_date(stamp)
        persisted = self.effects.load()
        state = deepcopy(persisted)
        active = state.get("active_run")
        if isinstance(active, dict):
            return self._resume(
                stamp, today, persisted, state, cast(ReleaseState, active)
            )
        return self._start(stamp, today, persisted, state, dry_run)

    def _resume(
        self,
        stamp: datetime,
        today: date,
        persisted: ReleaseState,
        state: ReleaseState,
        active: ReleaseState,
    ) -> OpenedReleaseRun:
        artists = self.effects.restore(active)
        start, end, run_id = _active_window(active)
        return OpenedReleaseRun(
            stamp,
            today,
            persisted,
            state,
            active,
            artists,
            start,
            end,
            run_id,
            True,
            None,
        )

    def _start(
        self,
        stamp: datetime,
        today: date,
        persisted: ReleaseState,
        state: ReleaseState,
        dry_run: bool,
    ) -> OpenedReleaseRun:
        refreshed = self.effects.refresh(stamp)
        artists = self.effects.rank(refreshed.history)
        if not artists:
            raise ReleaseCheckError(
                f"No Last.fm artists have at least {self.minimum_scrobbles} scrobbles."
            )
        start = _window_start(state.get("last_checked_through"), today)
        run_id = self.run_id(stamp)
        active = _active_record(run_id, stamp, start, today, artists)
        state["active_run"] = active
        if not dry_run:
            self.effects.persist(state)
            self.effects.audit(
                run_id,
                "run_started",
                checked_from=start.isoformat(),
                checked_through=today.isoformat(),
                artists=len(artists),
            )
        return OpenedReleaseRun(
            stamp,
            today,
            persisted,
            state,
            active,
            artists,
            start,
            today,
            run_id,
            False,
            refreshed,
        )
