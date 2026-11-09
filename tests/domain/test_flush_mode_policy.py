"""Exercise independent activation, exit and override decisions at exact edges."""

from dataclasses import replace

import pytest

from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.domain.flush_mode import automatic_flush
from spotify_manager.domain.flush_mode import discovery_fallback
from spotify_manager.domain.flush_mode import flush_reason


@pytest.mark.parametrize(
    "previous,queue,second,expected",
    [
        (False, 2399, 1199, False),
        (False, 2400, 0, True),
        (False, 0, 1200, True),
        (False, 2401, 1201, True),
        (True, 1200, 900, False),
        (True, 1199, 899, False),
        (True, 1201, 900, True),
        (True, 1200, 901, True),
        (True, 2399, 1199, True),
        (False, 1201, 901, False),
    ],
)
def test_exact_thresholds_and_hysteresis(
    previous: bool, queue: int, second: int, expected: bool
) -> None:
    """Either activation edge and both exit edges control the automatic state.

    Args:
        previous: Prior automatic state.
        queue: Observed first queue size.
        second: Observed second queue size.
        expected: Required next automatic state.
    """
    assert automatic_flush(previous, QueueCounts(queue, second)) is expected


@pytest.mark.parametrize(
    "control,active", [("automatic", True), ("on", True), ("off", False)]
)
def test_manual_control_is_independent(control: FlushControl, active: bool) -> None:
    """The manual selection overrides only the effective decision.

    Args:
        control: Operator selection.
        active: Expected effective mode.
    """
    state = FlushState(control=control, automatic_active=True)
    assert state.active is active and state.automatic_active
    assert replace(state, control="automatic").active


@pytest.mark.parametrize(
    "state,fragment",
    [
        (FlushState(), "No successful"),
        (FlushState(control="on"), "forced on"),
        (FlushState(control="off"), "forced off"),
        (FlushState(counts=QueueCounts(10, 10)), "normal"),
        (FlushState(automatic_active=True, counts=QueueCounts(2400, 0)), "2,400"),
        (FlushState(automatic_active=True, counts=QueueCounts(0, 1200)), "1,200"),
        (FlushState(automatic_active=True, counts=QueueCounts(1300, 950)), "Waiting"),
    ],
)
def test_reason_describes_effective_policy(state: FlushState, fragment: str) -> None:
    """The reason distinguishes overrides, activation and retained hysteresis.

    Args:
        state: Policy snapshot.
        fragment: Required operator-facing context.
    """
    assert fragment in flush_reason(state)


@pytest.mark.parametrize(
    "restricted,after,allowed",
    [(True, 9, True), (True, 10, False), (True, 11, False), (False, 0, False)],
)
def test_capacity_exception_is_bounded(
    restricted: bool, after: int, allowed: bool
) -> None:
    """Discovery is a capacity exception after a restricted pass.

    Args:
        restricted: Whether recovery eligibility was required.
        after: Size after recovery.
        allowed: Whether another pass may fill remaining slots.
    """
    assert discovery_fallback(restricted, after, 10) is allowed
