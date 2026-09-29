"""History refresh contracts without filesystem, SDK, settings or bootstrap imports."""

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.application.history_refresh import HistoryExport
from spotify_manager.application.history_refresh import HistoryRecord
from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.history_values import ScrobbleHistoryCancelledError
from spotify_manager.application.history_values import ScrobbleHistoryError
from spotify_manager.application.history_values import ScrobbleHistorySummary


def _record(title: str = "Song", timestamp: int = 1000) -> HistoryRecord:
    return {"artist": "Björk", "track": title, "album": "Álbum", "date": timestamp}


def _export() -> HistoryExport:
    return HistoryExport(
        {"username": " user ", "extra": "retained"}, [_record()], False
    )


@dataclass
class HistoryMemory:
    """Observe refresh ordering and retain accepted in-memory effects.

    Args:
        export: Original validated history.
        delta: Legacy overlap and new records.
        live: Live overlap and new records.
        events: Ordered workflow observations.
        messages: Presented progress.
        saved: Accepted replacements.
        summaries: Accepted audits.
        cancel_at: One-based cancellation check to interrupt.
        checks: Observed cancellation checks.
        failure: Effect that fails after observation.
        requests: Inclusive API ranges.
    """

    export: HistoryExport = field(default_factory=_export)
    delta: tuple[HistoryRecord, ...] = ()
    live: tuple[HistoryRecord, ...] = ()
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    saved: list[tuple[dict[str, object], list[HistoryRecord]]] = field(
        default_factory=list
    )
    summaries: list[ScrobbleHistorySummary] = field(default_factory=list)
    cancel_at: int = 0
    checks: int = 0
    failure: str = ""
    requests: list[tuple[int, int]] = field(default_factory=list)

    def _step(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def hydrate(self) -> None:
        """Observe managed hydration."""
        self._step("hydrate")

    def load(self) -> HistoryExport:
        """Return validated original contents.

        Returns:
            Caller-owned export.
        """
        self._step("load")
        return self.export

    def legacy(self) -> tuple[HistoryRecord, ...]:
        """Return legacy records.

        Returns:
            Delta in original order.
        """
        self._step("legacy")
        return self.delta

    def backup(self, export: HistoryExport, checked_at: datetime) -> Path:
        """Observe backup before replacement.

        Args:
            export: Original export, including fallback provenance.
            checked_at: Effective refresh time.

        Returns:
            Stable backup path.
        """
        self._step("backup")
        assert export is self.export
        assert checked_at == datetime.fromtimestamp(10, UTC)
        return Path("backup.gz")

    def write(self, payload: dict[str, object], records: list[HistoryRecord]) -> None:
        """Accept a replacement after the optional failure.

        Args:
            payload: Updated metadata.
            records: Complete history in timestamp order.
        """
        self._step("write")
        self.saved.append((payload, records))

    def mark(self, checked_at: datetime) -> None:
        """Observe successful-check timestamp recording.

        Args:
            checked_at: Effective refresh time.
        """
        self._step("mark")

    def publish(self, full_rebuild: bool) -> None:
        """Observe publication after timestamp recording.

        Args:
            full_rebuild: Original source description selector.
        """
        self._step("publish")

    def audit(self, summary: ScrobbleHistorySummary) -> None:
        """Accept the final audit.

        Args:
            summary: Completed refresh.
        """
        self._step("audit")
        self.summaries.append(summary)

    def fetch(self, start: int, end: int) -> Iterable[HistoryRecord]:
        """Observe the API range.

        Args:
            start: Inclusive lower UTC second.
            end: Inclusive upper UTC second.

        Returns:
            Live records in response order.
        """
        self._step("fetch")
        self.requests.append((start, end))
        return self.live

    def clock(self) -> datetime:
        """Observe clock access.

        Returns:
            Stable effective time.
        """
        self._step("clock")
        return datetime.fromtimestamp(10, UTC)

    def cancel(self) -> None:
        """Observe cancellation at each boundary.

        Raises:
            ScrobbleHistoryCancelledError: The selected check is reached.
        """
        self._step("cancel")
        self.checks += 1
        if self.checks == self.cancel_at:
            raise ScrobbleHistoryCancelledError("cancelled")


def _workflow(memory: HistoryMemory) -> HistoryRefresh:
    return HistoryRefresh(
        memory, memory.fetch, memory.clock, memory.cancel, memory.messages.append
    )


@pytest.mark.parametrize("dry_run", [False, True])
def test_overlap_counts_extra_occurrences_and_preserves_record_order(
    dry_run: bool,
) -> None:
    """Merge occurrence counts separately for legacy and live overlap.

    Args:
        dry_run: Whether persistence is suppressed.
    """
    original = _record()
    original["albumId"] = "retained"
    overlap = dict(_record(), artist="bjork", album="album")
    memory = HistoryMemory(
        delta=(overlap, overlap),
        live=(overlap, overlap, overlap, _record("Earlier", 500)),
    )
    memory.export.records[:] = [original]
    result = _workflow(memory).run("USER", dry_run, False)
    assert (
        result.export_scrobbles,
        result.legacy_scrobbles_added,
        result.live_scrobbles_added,
    ) == (1, 1, 2)
    assert [play.track for play in result.history] == [
        "Earlier",
        "Song",
        "Song",
        "Song",
    ]
    assert [play.artist for play in result.history] == [
        "Björk",
        "Björk",
        "bjork",
        "bjork",
    ]
    assert result.total_scrobbles == 4 and result.username == "user"
    assert memory.requests == [(1, 10)]
    assert memory.export.records == [original]
    assert result.persisted is not dry_run
    if dry_run:
        assert not memory.saved and not memory.summaries
        return
    assert memory.saved[0][0] is memory.export.payload
    assert memory.saved[0][1][1] is original
    assert result.backup_path == Path("backup.gz")
    assert memory.summaries == [result]


@pytest.mark.parametrize("recovered", [False, True])
def test_unchanged_history_marks_and_publishes_without_backup(recovered: bool) -> None:
    """Keep publication on successful checks, including fallback recovery.

    Args:
        recovered: Whether the export came from fallback parts.
    """
    memory = HistoryMemory(live=(_record(),))
    memory.export = HistoryExport(
        memory.export.payload, memory.export.records, recovered
    )
    result = _workflow(memory).run(None, False, False)
    assert not result.persisted and result.backup_path is None
    assert memory.events[-3:] == ["mark", "publish", "audit"]
    assert "backup" not in memory.events
    assert (
        memory.messages[-1] == "History already current; recorded successful check time"
    )
    assert (
        "Recovered Last.fm history from compressed fallback parts" in memory.messages
    ) is recovered


@pytest.mark.parametrize("dry_run", [False, True])
def test_rebuild_ignores_legacy_and_replaces_history(dry_run: bool) -> None:
    """Full rebuild starts at zero and stamps only the replacement metadata.

    Args:
        dry_run: Whether replacement effects are suppressed.
    """
    memory = HistoryMemory(delta=(_record("Legacy"),), live=(_record("Corrected"),))
    result = _workflow(memory).run(None, dry_run, True)
    assert memory.requests == [(0, 10)]
    assert "legacy" not in memory.events
    assert result.legacy_scrobbles_added == 0 and result.live_scrobbles_added == 1
    assert result.history[0].track == "Corrected"
    assert "full_rebuilt_at" not in memory.export.payload
    assert "Rebuilding all scrobbles from Last.fm" in memory.messages
    if dry_run:
        assert not memory.saved
        return
    assert memory.saved[0][0] == dict(
        memory.export.payload, full_rebuilt_at=memory.clock().isoformat()
    )


def test_rebuild_stamp_prevents_deleted_legacy_from_returning() -> None:
    """A truthy rebuild stamp suppresses the legacy delta on later refreshes."""
    memory = HistoryMemory(delta=(_record("Deleted"),))
    memory.export.payload["full_rebuilt_at"] = "recorded"
    result = _workflow(memory).run(None, False, False)
    assert "legacy" not in memory.events
    assert result.total_scrobbles == 1


@pytest.mark.parametrize(
    "username,expected,result",
    [("", "Expected", "Expected"), ("", None, ""), ("user", "", "user")],
)
def test_username_fallback(username: str, expected: str | None, result: str) -> None:
    """Preserve optional ownership constraints and original fallback spelling.

    Args:
        username: Export account name.
        expected: Optional expected account.
        result: Effective summary account name.
    """
    memory = HistoryMemory()
    memory.export.payload["username"] = username
    assert _workflow(memory).run(expected, True, False).username == result


def test_username_mismatch_stops_before_legacy_and_api_reads() -> None:
    """Reject ownership mismatches after hydration and export observation."""
    memory = HistoryMemory()
    with pytest.raises(ScrobbleHistoryError, match="belongs to user, not other"):
        _workflow(memory).run("other", False, False)
    assert memory.events == ["hydrate", "cancel", "clock", "load", "cancel"]


def test_future_local_history_skips_live_request() -> None:
    """Preserve the no-request path when local timestamps exceed the check time."""
    memory = HistoryMemory()
    memory.export.records[:] = [_record(timestamp=11000)]
    result = _workflow(memory).run(None, False, False)
    assert not memory.requests
    assert memory.checks == 3 and result.live_scrobbles_added == 0


def test_empty_incremental_history_fails_before_fetch() -> None:
    """Empty local history requires an explicit rebuild."""
    memory = HistoryMemory()
    memory.export.records.clear()
    with pytest.raises(ScrobbleHistoryError, match="history is empty"):
        _workflow(memory).run(None, False, False)
    assert not memory.requests


def test_empty_rebuild_cannot_replace_existing_history() -> None:
    """An empty API response leaves nonempty history untouched."""
    memory = HistoryMemory()
    with pytest.raises(ScrobbleHistoryError, match="empty API response"):
        _workflow(memory).run(None, False, True)
    assert "backup" not in memory.events and memory.checks == 3


def test_empty_rebuild_can_replace_empty_history() -> None:
    """An explicitly rebuilt empty export still persists its rebuild stamp."""
    memory = HistoryMemory()
    memory.export.records.clear()
    result = _workflow(memory).run(None, False, True)
    assert result.persisted and not result.history
    assert memory.saved[0][1] == []


@pytest.mark.parametrize("check", [1, 2, 3, 4])
def test_cancellation_stops_before_any_persistence(check: int) -> None:
    """Check cancellation before loading, merging live records and persistence.

    Args:
        check: Boundary to interrupt.
    """
    memory = HistoryMemory(live=(_record("New"),), cancel_at=check)
    with pytest.raises(ScrobbleHistoryCancelledError):
        _workflow(memory).run(None, False, False)
    assert memory.checks == check and "backup" not in memory.events
    assert memory.events[0] == "hydrate" and memory.events[-1] == "cancel"


@pytest.mark.parametrize("failure", ["backup", "write", "mark", "publish", "audit"])
def test_effect_failure_prevents_later_effects(failure: str) -> None:
    """Keep the original failure order after merging succeeds.

    Args:
        failure: Injected effect failure.
    """
    memory = HistoryMemory(live=(_record("New"),), failure=failure)
    with pytest.raises(OSError, match=failure):
        _workflow(memory).run(None, False, False)
    effects = ["backup", "write", "mark", "publish", "audit"]
    assert (
        memory.events[-(effects.index(failure) + 1) :]
        == effects[: effects.index(failure) + 1]
    )
    assert bool(memory.saved) is (failure in {"mark", "publish", "audit"})
    assert not memory.summaries
