"""Refresh effect ordering contracts captured before moving orchestration."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from functools import partialmethod
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.legacy.history_refresh import LegacyHistoryStorage
from spotify_manager.routines import scrobble_history as routine
from tests.support.history_dependencies import hydrate_history


@dataclass
class RefreshBoundary:
    """Record observable refresh steps and fail at one chosen boundary.

    Args:
        failure: Step that raises after being observed.
        events: Ordered observations.
    """

    failure: str = ""
    events: list[str] = field(default_factory=list)

    def step(self, name: str) -> None:
        """Record a step, raising at the configured failure boundary.

        Args:
            name: Observed operation.

        Raises:
            OSError: The chosen boundary was reached.
        """
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def artifact(self, path: Path) -> str:
        """Identify the managed history artifact.

        Args:
            path: Requested export.

        Returns:
            The managed artifact name.
        """
        return "scrobbles"

    def service(self) -> RefreshBoundary:
        """Return the recording service.

        Returns:
            This fixture.
        """
        return self

    def hydrate(self, name: str) -> None:
        """Record hydration.

        Args:
            name: Managed artifact.
        """
        self.step("hydrate")

    def publish(self, name: str, *, source: str) -> None:
        """Record publication.

        Args:
            name: Managed artifact.
            source: Refresh description.
        """
        self.step("publish")

    def cancel(self) -> bool:
        """Record each cancellation check.

        Returns:
            False, allowing work to continue.
        """
        self.step("cancel")
        return False

    def load(
        self, path: Path
    ) -> tuple[dict[str, object], list[dict[str, object]], bool]:
        """Return a validated export with one old play.

        Args:
            path: Requested export.

        Returns:
            Payload, records and fallback flag.
        """
        self.step("load")
        records: list[dict[str, object]] = [
            {"track": "Old", "artist": "Artist", "album": "Album", "date": 1000}
        ]
        return {"username": "user", "scrobbles": records}, records, False

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Observe the request and return a new play.

        Args:
            from_timestamp: Inclusive lower bound.
            to_timestamp: Inclusive upper bound.
            limit: Existing page size.

        Returns:
            One new dated play.
        """
        self.step("fetch")
        assert (from_timestamp, to_timestamp, limit) == (1, 10, 200)
        return (LastFmRecentTrack("Artist", "New", "Album", 2),)

    def backup(
        self,
        path: Path,
        directory: Path,
        checked_at: datetime,
        recovered_payload: dict[str, object] | None = None,
    ) -> Path:
        """Record backup creation.

        Args:
            path: Original export.
            directory: Backup directory.
            checked_at: Refresh timestamp.
            recovered_payload: Optional fallback contents.

        Returns:
            The backup path.
        """
        self.step("backup")
        return directory / "backup.gz"

    def write(
        self, path: Path, payload: dict[str, object], records: list[dict[str, object]]
    ) -> None:
        """Record replacement after all merging.

        Args:
            path: Destination export.
            payload: Original metadata.
            records: Merged records.
        """
        self.step("write")
        assert len(records) == 2

    def mark(self, path: Path, checked_at: datetime) -> None:
        """Record the successful-check timestamp update.

        Args:
            path: Export to mark.
            checked_at: Refresh timestamp.
        """
        self.step("mark")

    def audit(self, summary: routine.ScrobbleHistorySummary, path: Path) -> None:
        """Record the final audit.

        Args:
            summary: Completed refresh.
            path: Audit destination.
        """
        self.step("audit")
        assert summary.persisted


def _install(boundary: RefreshBoundary, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        LegacyHistoryStorage,
        "hydrate",
        partialmethod(hydrate_history, cast(LibraryDataService, boundary)),
    )
    monkeypatch.setattr(routine, "_load_export", boundary.load)
    monkeypatch.setattr(routine, "_backup_export", boundary.backup)
    monkeypatch.setattr(routine, "_write_export_atomic", boundary.write)
    monkeypatch.setattr(routine, "_mark_export_checked", boundary.mark)
    monkeypatch.setattr(routine, "_append_log", boundary.audit)


def _refresh(
    boundary: RefreshBoundary, dry_run: bool
) -> routine.ScrobbleHistorySummary:
    return routine.refresh_scrobble_history(
        boundary,
        legacy_delta_path=None,
        now=datetime.fromtimestamp(10, UTC),
        cancel_check=boundary.cancel,
        dry_run=dry_run,
    )


@pytest.mark.parametrize(
    "failure", ["hydrate", "fetch", "backup", "write", "mark", "publish", "audit"]
)
def test_failure_stops_after_accepted_effects(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain accepted effects and suppress every later step on failure.

    Args:
        failure: Step that fails.
        monkeypatch: Temporary boundary replacement.
    """
    boundary = RefreshBoundary(failure)
    _install(boundary, monkeypatch)
    expected = [
        "hydrate",
        "cancel",
        "load",
        "cancel",
        "fetch",
        "cancel",
        "cancel",
        "backup",
        "write",
        "mark",
        "publish",
        "audit",
    ]
    with pytest.raises(OSError, match=failure):
        _refresh(boundary, False)
    assert boundary.events == expected[: expected.index(failure) + 1]


def test_preview_still_hydrates_and_checks_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview retains observations but suppresses persistence and publication.

    Args:
        monkeypatch: Temporary boundary replacement.
    """
    boundary = RefreshBoundary()
    _install(boundary, monkeypatch)
    result = _refresh(boundary, True)
    assert boundary.events == [
        "hydrate",
        "cancel",
        "load",
        "cancel",
        "fetch",
        "cancel",
        "cancel",
    ]
    assert result.total_scrobbles == 2
    assert not result.persisted
