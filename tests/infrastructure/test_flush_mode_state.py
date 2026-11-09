"""Exercise stored policy validation and actual compare-and-swap collisions."""

from pathlib import Path

import pytest

from spotify_manager.core.state.definitions import ObjectDefinition
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.flush_mode import FlushChange
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.infrastructure.flush_mode_schema import FlushModeDefinition
from spotify_manager.infrastructure.flush_mode_schema import decode_flush_state
from spotify_manager.infrastructure.flush_mode_state import FlushModeState
from spotify_manager.infrastructure.persistence.json_state_store import JsonStateStore


STAMP = "2026-11-09T00:00:00+00:00"


class InterleavedStateStore(JsonStateStore):
    """Commit a competing policy update just before one guarded publication.

    Args:
        path: Test-owned shared state path.
    """

    def __init__(self, path: Path) -> None:
        """Start with no pending competing update.

        Args:
            path: Test-owned shared state path.
        """
        super().__init__(path)
        self.competing: FlushChange | None = None

    def write(
        self, document: dict[str, object], *, expected_revision: str, message: str
    ) -> StateSnapshot:
        """Make a real conflicting commit through the same central service.

        Args:
            document: Original guarded candidate.
            expected_revision: Original optimistic baseline.
            message: Original commit description.

        Returns:
            Stored document, after a possible real revision conflict.
        """
        pending = self.competing
        self.competing = None
        if pending is not None:
            FlushModeState(StateService(self)).change(pending)
        return super().write(
            document, expected_revision=expected_revision, message=message
        )


def test_new_namespace_is_read_only_until_a_change(tmp_path: Path) -> None:
    """Default inspection cannot manufacture a successful check or state file.

    Args:
        tmp_path: Isolated state directory.
    """
    path = tmp_path / "state.json"
    state = FlushModeState(StateService(JsonStateStore(path))).load()
    assert state == FlushState() and not path.exists()


def test_count_commit_rebases_over_operator_override(tmp_path: Path) -> None:
    """A CAS collision replays counts against the latest control selection.

    Args:
        tmp_path: Isolated state directory.
    """
    store = InterleavedStateStore(tmp_path / "state.json")
    mode = FlushModeState(StateService(store))
    store.competing = FlushChange(control="off")
    result = mode.change(
        FlushChange(counts=QueueCounts(2400, 0), started=STAMP, completed=STAMP)
    )
    assert result.control == "off" and result.automatic_active and not result.active
    assert mode.load() == result


def test_control_commit_preserves_concurrent_observations(tmp_path: Path) -> None:
    """Operator changes never discard a successful check committed concurrently.

    Args:
        tmp_path: Isolated state directory.
    """
    store = InterleavedStateStore(tmp_path / "state.json")
    service = StateService(store)
    other = service.namespace("unrelated", ObjectDefinition())
    other.load()
    other.save({"accepted_plan": ["keep"]})
    mode = FlushModeState(service)
    store.competing = FlushChange(
        counts=QueueCounts(20, 30), started=STAMP, completed=STAMP
    )
    result = mode.change(FlushChange(control="on"))
    assert result.active and result.counts == QueueCounts(20, 30)
    assert service.namespace("unrelated", ObjectDefinition()).load() == {
        "accepted_plan": ["keep"]
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("control", "invalid"),
        ("control", {}),
        ("automatic_active", 1),
        ("counts", {"queue": True, "queue_2": 1}),
        ("counts", {"queue": -1, "queue_2": 1}),
        ("counts", {"queue": 1}),
        ("checked_at", "not a date"),
        ("attempted_at", "2026-11-09"),
        ("error", 3),
    ],
)
def test_invalid_policy_is_never_treated_as_normal(field: str, value: object) -> None:
    """Malformed shared control fails closed instead of resetting mode.

    Args:
        field: Corrupted namespace field.
        value: Invalid external JSON value.
    """
    raw = FlushModeDefinition().default()
    raw[field] = value
    with pytest.raises(StateDocumentError):
        decode_flush_state(raw)
