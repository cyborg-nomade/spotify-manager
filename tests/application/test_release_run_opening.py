"""Independent opening, resume authority and accepted-start failures."""

from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from typing import cast

import pytest

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.release_check_values import ReleaseCheckError
from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.application.release_opening import ReleaseRunOpening
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import RankedArtist


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
ARTIST = RankedArtist("artist", "Artist", 100, 1)
RUN_ID = "20260925T000000000000Z"
HISTORY = ScrobbleHistorySummary(STAMP, "user", (), 100, 0, 2, False, True, None)


def _active() -> ReleaseState:
    return {
        "run_id": "resumed",
        "started_at": STAMP.isoformat(),
        "checked_from": "2025-12-31",
        "checked_through": "2026-09-01",
        "artists": [asdict(ARTIST)],
        "completed_artist_keys": [],
        "pending_release_id": None,
    }


@dataclass
class Effects:
    """Record deterministic clock, state, history and accepted-start observations.

    Args:
        state: Original loaded opaque payload.
        artists: Original newly ranked or frozen artists.
        failure: Boundary to fail after recording acceptance.
    """

    state: ReleaseState = field(default_factory=dict)
    artists: tuple[RankedArtist, ...] = (ARTIST,)
    failure: str | None = None
    events: list[str] = field(default_factory=list)
    saved: list[ReleaseState] = field(default_factory=list)
    audits: list[tuple[str, str, ReleaseState]] = field(default_factory=list)

    def _record(self, event: str) -> None:
        self.events.append(event)
        if event == self.failure:
            raise RuntimeError(event)

    def clock(self) -> datetime:
        """Resolve the original effective UTC timestamp.

        Returns:
            Deterministic original timestamp.
        """
        self._record("clock")
        return STAMP

    def local_date(self, stamp: datetime) -> date:
        """Resolve the original local calendar date before acquiring state.

        Args:
            stamp: Effective UTC timestamp.

        Returns:
            Deterministic original local date.
        """
        self._record("date")
        assert stamp == STAMP
        return stamp.date()

    def run_id(self, stamp: datetime) -> str:
        """Resolve the original new-run identity after window validation.

        Args:
            stamp: Effective UTC timestamp.

        Returns:
            Original sortable identifier.
        """
        self._record("run_id")
        assert stamp == STAMP
        return RUN_ID

    def load(self) -> ReleaseState:
        """Observe the original opaque state after date resolution.

        Returns:
            Original mutable payload without changes.
        """
        self._record("load")
        return self.state

    def refresh(self, stamp: datetime) -> ScrobbleHistorySummary:
        """Perform the original actual history refresh before new ranking.

        Args:
            stamp: Effective UTC timestamp.

        Returns:
            Original history outcome.
        """
        self._record("refresh")
        assert stamp == STAMP
        return HISTORY

    def rank(self, history: tuple[Scrobble, ...]) -> tuple[RankedArtist, ...]:
        """Observe original new-run ranking.

        Args:
            history: Original refreshed canonical plays.

        Returns:
            Original ranked eligible artists.
        """
        self._record("rank")
        assert history == HISTORY.history
        return self.artists

    def restore(self, active: ReleaseState) -> tuple[RankedArtist, ...]:
        """Observe original frozen ranking before validating the active window.

        Args:
            active: Original persisted active run.

        Returns:
            Original frozen artists.
        """
        self._record("restore")
        assert active == self.state["active_run"]
        return self.artists

    def persist(self, state: ReleaseState) -> None:
        """Record accepted original checkpoint before a possible later failure.

        Args:
            state: Original complete working payload.
        """
        state["updated_at"] = STAMP.isoformat()
        self.saved.append(deepcopy(state))
        self._record("persist")

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Record accepted original start event after the initial checkpoint.

        Args:
            run_id: Original durable identity.
            event: Original event name.
            details: Original ordered event fields.
        """
        self.audits.append((run_id, event, details))
        self._record("audit")


def _workflow(effects: Effects) -> ReleaseRunOpening:
    return ReleaseRunOpening(effects, effects.clock, effects.local_date, effects.run_id)


EVENTS = ["clock", "date", "load", "refresh", "rank", "run_id", "persist", "audit"]


@pytest.mark.parametrize("failure", EVENTS)
def test_release_opening_failure_prefix(failure: str) -> None:
    """Protect clock order and checkpoints before a later audit failure.

    Args:
        failure: Original observed boundary.
    """
    effects = Effects(failure=failure)
    with pytest.raises(RuntimeError, match=failure):
        _workflow(effects).run(False)
    assert effects.events == EVENTS[: EVENTS.index(failure) + 1]
    assert bool(effects.saved) is (EVENTS.index(failure) >= EVENTS.index("persist"))
    assert bool(effects.audits) is (failure == "audit")


@pytest.mark.parametrize("preview", [False, True])
def test_release_opening_fresh_state_and_preview(preview: bool) -> None:
    """Retain actual history refresh, original deep copy and preview state isolation.

    Args:
        preview: Original release-preview mode.
    """
    original: ReleaseState = {"operator": {"keep": "original"}, "active_run": None}
    effects = Effects(state=original)
    opened = _workflow(effects).run(preview)
    assert effects.events == (EVENTS[:6] if preview else EVENTS)
    assert opened.persisted_state is original and opened.state is not original
    assert opened.history_refresh is HISTORY and opened.artists == (ARTIST,)
    assert not opened.resumed and opened.checked_from == date(2026, 1, 1)
    assert opened.checked_through == STAMP.date() and opened.run_id == RUN_ID
    assert original == {"operator": {"keep": "original"}, "active_run": None}
    cast(ReleaseState, opened.state["operator"])["keep"] = "changed"
    assert original["operator"] == {"keep": "original"}
    assert opened.active is opened.state["active_run"]


@pytest.mark.parametrize(
    "previous,expected",
    [
        (None, date(2026, 1, 1)),
        (12, date(2026, 1, 1)),
        ("2025-12-31", date(2025, 12, 31)),
        ("2026-08-31", date(2026, 1, 1)),
    ],
)
def test_release_opening_original_window_start(
    previous: object, expected: date
) -> None:
    """Preserve original earliest previous-check/year-start rule and nonstring fallback.

    Args:
        previous: Original persisted semantic date.
        expected: Original inclusive check-window start.
    """
    effects = Effects(state={"last_checked_through": previous})
    assert _workflow(effects).run(True).checked_from == expected


def test_release_opening_invalid_previous_after_history_before_checkpoint() -> None:
    """Retain original refresh/ranking before previous-window validation failure."""
    effects = Effects(state={"last_checked_through": "invalid"})
    with pytest.raises(
        ReleaseCheckStateError, match="previous release-check date"
    ) as error:
        _workflow(effects).run(False)
    assert isinstance(error.value.__cause__, ValueError)
    assert effects.events == EVENTS[:5]
    assert effects.saved == [] and effects.audits == []


def test_release_opening_no_eligible_artists_after_refresh() -> None:
    """Retain minimum errors before window parsing and start effects."""
    effects = Effects(state={"last_checked_through": "invalid"}, artists=())
    with pytest.raises(ReleaseCheckError, match="at least 100 scrobbles"):
        _workflow(effects).run(False)
    assert effects.events == EVENTS[:5]


@pytest.mark.parametrize("preview", [False, True])
def test_release_opening_resume_authority(preview: bool) -> None:
    """Resume the frozen ranking and window without refreshing history.

    Args:
        preview: Original release-preview mode.
    """
    active = _active()
    effects = Effects(state={"active_run": active, "last_checked_through": "invalid"})
    opened = _workflow(effects).run(preview)
    assert effects.events == EVENTS[:3] + ["restore"]
    assert opened.resumed and opened.history_refresh is None
    assert opened.checked_from == date(2025, 12, 31) and opened.checked_through == date(
        2026, 9, 1
    )
    assert opened.run_id == "resumed" and opened.artists == (ARTIST,)
    assert opened.active == active and opened.active is not active
    assert effects.saved == [] and effects.audits == []


@pytest.mark.parametrize(
    "key,missing",
    [("checked_from", False), ("checked_through", False), ("run_id", True)],
)
def test_release_opening_invalid_active_window(key: str, missing: bool) -> None:
    """Retain original frozen-ranking observation before narrowed active-window errors.

    Args:
        key: Original invalid/missing window field.
        missing: Remove the field rather than supplying an invalid date.
    """
    active = _active()
    if missing:
        active.pop(key)
    else:
        active[key] = "invalid"
    effects = Effects(state={"active_run": active})
    with pytest.raises(
        ReleaseCheckStateError, match="active release-check window"
    ) as error:
        _workflow(effects).run(False)
    assert isinstance(error.value.__cause__, (ValueError, KeyError))
    assert effects.events == EVENTS[:3] + ["restore"]


def test_release_opening_restore_error_precedes_window_validation() -> None:
    """Retain original invalid-ranking failure before a malformed persisted window."""
    active = _active()
    active["checked_from"] = "invalid"
    effects = Effects(state={"active_run": active}, failure="restore")
    with pytest.raises(RuntimeError, match="restore"):
        _workflow(effects).run(False)
    assert effects.events == EVENTS[:3] + ["restore"]
