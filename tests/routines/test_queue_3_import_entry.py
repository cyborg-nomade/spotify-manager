"""Standalone annual import preserves preparation, state cloning and progress order."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.state import BlockingRoutineState
from spotify_manager.routines import queue_3
from tests.routines.test_queue_3 import FakeSpotify
from tests.routines.test_queue_3_import_boundaries import ImportBoundaries
from tests.routines.test_queue_3_import_boundaries import _spotify


@dataclass
class ImportEntryBoundaries(ImportBoundaries):
    """Expose saved state and progress events around the original import entry.

    Args:
        completed: Whether the stored annual checkpoint suppresses import.
        loaded: Complete namespace returned to the caller without copying.
    """

    completed: bool = False
    loaded: dict[str, object] | None = None

    def load_namespace(self) -> dict[str, object]:
        """Return the same namespace so tests can detect preview mutation.

        Returns:
            A complete mutable Queue 3 namespace.
        """
        state = queue_3._default_state()
        state["annual_imports"] = {"2026": {"completed": self.completed}}
        self.loaded = state
        self._record("load", None)
        return state

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe the existing explicit progress callback.

        Args:
            done: Completed units.
            total: Total units.
            message: Original progress label.
        """
        self._record("progress", (done, total, message))


async def _run_entry(
    spotify: FakeSpotify, memory: ImportEntryBoundaries, preview: bool
) -> queue_3.AnnualImportSummary:
    return queue_3.import_previous_year_discoveries(
        cast(Spotify, spotify),
        "queue3",
        active_year=2026,
        dry_run=preview,
        echo=memory,
        progress_callback=memory,
        retry_call=memory,
        state_service=cast(queue_3.StateService, memory),
        log_path=Path("audit.jsonl"),
    )


def _state_access(
    path: Path, service: queue_3.StateService | None
) -> BlockingRoutineState:
    assert service is not None
    return ImportEntryState(cast(ImportEntryBoundaries, service))


@dataclass(frozen=True)
class ImportEntryState:
    """Supply the original synchronous state boundary below the async file view.

    Args:
        source: Existing checkpoint, progress and import observations.
    """

    source: ImportEntryBoundaries

    def load(self) -> dict[str, object]:
        """Read the same original mutable namespace.

        Returns:
            Original caller-owned state document.
        """
        return self.source.load_namespace()

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Accept the original checkpoint before later progress presentation.

        Args:
            value: Original complete checkpoint.
            message: Original optional storage message.
        """
        self.source.record_checkpoint(value, message=message)


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("completed", [False, True])
async def test_import_entry_preserves_preparation_progress_and_preview_clone(
    monkeypatch: pytest.MonkeyPatch, preview: bool, completed: bool
) -> None:
    """Completed records still observe the destination before loading stored state.

    Args:
        monkeypatch: Scoped audit and namespace adapter substitution.
        preview: Whether remote writes and working-state mutations are isolated.
        completed: Whether the annual checkpoint suppresses the source import.
    """
    memory = ImportEntryBoundaries(completed=completed)
    monkeypatch.setattr(queue_3, "_state_access", _state_access)
    monkeypatch.setattr(queue_3, "append_event", memory.audit)
    result = await _run_entry(_spotify(), memory, preview)
    names = [name for name, value in memory.events]
    assert names[0] == "progress"
    assert names.index("read") < names.index("load")
    assert names[-1] == "progress"
    assert ("checkpoint" in names) == (not completed and not preview)
    assert result.already_completed == completed and result.dry_run == preview
    assert result.additions == (0 if completed else 2)
    assert result.already_present == 0
    assert memory.loaded is not None
    imports = cast(dict[str, object], memory.loaded["annual_imports"])
    record = cast(dict[str, object], imports["2026"])
    assert record["completed"] == (completed or not preview)
    expected = "already imported" if completed else "Checked Great Discoveries 2025"
    assert expected in str(memory.events[-1][1])
