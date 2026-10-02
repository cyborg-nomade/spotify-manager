"""Pre-extraction recovery boundaries for executing a saved Queue 3 transition."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import queue_3
from tests.routines.test_queue_3 import FakeSpotify
from tests.routines.test_queue_3 import automatic_transition
from tests.routines.test_queue_3 import raw_release
from tests.routines.test_queue_3 import raw_track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


RELEASE = studio_release("album", "Album")
SOURCE = playlist_track("source", RELEASE)
TARGET = release_track("target")


@dataclass
class ExecutionBoundaries:
    """Observe accepted remote changes and durable acknowledgments of one saved plan.

    Args:
        state: Caller-owned working namespace returned by the load boundary.
        failure: Boundary interruption before acceptance.
        events: Ordered external boundary observations.
        checkpoint: Last accepted detached state checkpoint.
    """

    state: dict[str, object]
    failure: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)
    checkpoint: dict[str, object] | None = None

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if name == self.failure:
            raise OSError(name)

    def load(self) -> dict[str, object]:
        """Return the prepared mutable namespace.

        Returns:
            Original active run and completed annual import.
        """
        return self.state

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Accept a namespace only after its checkpoint failure boundary.

        Args:
            value: Complete working namespace.
            message: Optional original storage message.
        """
        self._record("checkpoint", deepcopy(value))
        self.checkpoint = deepcopy(value)

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Fail before the selected mutation and retain existing read behavior.

        Args:
            operation: Original SDK operation.
            description: Original retry description.

        Returns:
            Original simulated SDK response.
        """
        if description.startswith("adding "):
            self._record("add", description)
        if description.startswith("removing "):
            self._record("remove", description)
        return operation()

    def audit(self, path: Path, event_type: str, **details: object) -> None:
        """Observe transition audits before state acknowledgment.

        Args:
            path: Original audit path.
            event_type: Original transition event type.
            details: Original result payload.
        """
        self._record("audit", (event_type, details))

    def echo(self, message: str) -> None:
        """Observe messages following each accepted playlist operation.

        Args:
            message: Original operator-facing message.
        """
        self._record("message", message)


def _state() -> dict[str, object]:
    entry: dict[str, object] = {
        "source": asdict(SOURCE),
        "artist_id": "artist",
        "artist_name": "Artist",
        "status": "pending",
        "plan": {
            "action": "advance",
            "current_release": asdict(RELEASE),
            "target_release": asdict(RELEASE),
            "target": asdict(TARGET),
            "evaluation": None,
            "reason": None,
        },
    }
    return {
        "version": 1,
        "annual_imports": {"2026": {"completed": True}},
        "composer_routes": {},
        "release_orders": {},
        "active_run": {
            "run_id": "saved-run",
            "playlist_id": "queue3",
            "status": "active",
            "entries": [entry],
        },
    }


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    album = raw_release("album", "Album", artist_id="artist")
    source = raw_track("source", "source", album, artist_id="artist")
    target = raw_track("target", "target", album, artist_id="artist")
    spotify.playlists["queue3"] = [source]
    spotify.release_tracks["album"] = [source, target]
    return spotify


def _access(path: Path, service: queue_3.StateService | None) -> queue_3.RoutineState:
    assert service is not None
    return cast(queue_3.RoutineState, service)


def _run(spotify: FakeSpotify, memory: ExecutionBoundaries) -> queue_3.FlushSummary:
    return queue_3.flush_queue_3(
        cast(Spotify, spotify),
        "queue3",
        automatic_transition,
        active_year=2026,
        retry_call=memory.retry,
        echo=memory.echo,
        state_service=cast(queue_3.StateService, memory),
    )


def _entry(state: dict[str, object]) -> dict[str, object]:
    run = cast(dict[str, object], state["active_run"])
    return cast(list[dict[str, object]], run["entries"])[0]


@pytest.mark.parametrize(
    "failure", [None, "add", "remove", "audit", "checkpoint", "message"]
)
def test_original_saved_transition_preserves_failure_acknowledgment_order(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    """Append precedes removal; result audit precedes entry status and checkpoint.

    Args:
        monkeypatch: Scoped persistence and audit boundary substitution.
        failure: Original boundary interrupted before acceptance.
    """
    memory = ExecutionBoundaries(_state(), failure)
    spotify = _spotify()
    monkeypatch.setattr(queue_3, "_state_access", _access)
    monkeypatch.setattr(queue_3, "append_event", memory.audit)
    if failure is not None:
        with pytest.raises(OSError, match=failure):
            _run(spotify, memory)
    else:
        result = _run(spotify, memory)
        assert result.resumed is True and result.advanced == 1
    assert _entry(memory.state)["status"] == (
        "completed" if failure in {None, "checkpoint"} else "pending"
    )
    expected = ["source"] if failure == "add" else ["source", "target"]
    if failure in {None, "audit", "checkpoint"}:
        expected = ["target"]
    assert [track["id"] for track in spotify.playlists["queue3"]] == expected
    assert (memory.checkpoint is not None) == (failure is None)
    if failure is None:
        assert [name for name, value in memory.events] == [
            "add",
            "message",
            "remove",
            "message",
            "audit",
            "checkpoint",
            "checkpoint",
        ]


def test_original_resumed_ordinary_cleanup_includes_existing_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing same-artist replacement remains part of ordinary snapshot cleanup.

    Args:
        monkeypatch: Scoped persistence and audit boundary substitution.
    """
    memory = ExecutionBoundaries(_state())
    spotify = _spotify()
    spotify.playlists["queue3"] = [spotify.release_tracks["album"][1]]
    monkeypatch.setattr(queue_3, "_state_access", _access)
    monkeypatch.setattr(queue_3, "append_event", memory.audit)
    result = _run(spotify, memory)
    assert result.advanced == 1 and result.resumed is True
    assert spotify.playlists["queue3"] == []
    assert spotify.mutations == [("remove", "target")]


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("entries", False, "active run has invalid entries"),
        ("release_orders", False, "release-order state is invalid"),
        ("composer_routes", False, "composer-route state is invalid"),
    ],
)
def test_original_resumed_run_validates_containers_before_entry_effects(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    """Invalid resumed records preserve the original validation boundary.

    Args:
        monkeypatch: Scoped persistence and audit substitution.
        field: Container to corrupt.
        value: Original malformed value.
        message: Expected Queue 3 state error text.
    """
    memory = ExecutionBoundaries(_state())
    if field == "entries":
        run = cast(dict[str, object], memory.state["active_run"])
        run[field] = value
    else:
        memory.state[field] = value
    monkeypatch.setattr(queue_3, "_state_access", _access)
    monkeypatch.setattr(queue_3, "append_event", memory.audit)
    with pytest.raises(queue_3.Queue3StateError, match=message):
        _run(_spotify(), memory)
    assert memory.events == []


@pytest.mark.parametrize("status", ["completed", "skipped"])
def test_original_acknowledged_entries_skip_decoding_and_only_finish_run(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """Acknowledged entries do not need a valid source or saved plan on resume.

    Args:
        monkeypatch: Scoped persistence and audit substitution.
        status: Existing acknowledged entry status.
    """
    memory = ExecutionBoundaries(_state())
    entry = _entry(memory.state)
    entry.update(status=status, source=None, plan=None)
    monkeypatch.setattr(queue_3, "_state_access", _access)
    monkeypatch.setattr(queue_3, "append_event", memory.audit)
    result = _run(_spotify(), memory)
    assert result.total == 1 and result.processed == 0 and result.resumed is True
    assert [name for name, value in memory.events] == ["checkpoint"]
    run = cast(dict[str, object], memory.state["active_run"])
    assert run["status"] == "completed"
