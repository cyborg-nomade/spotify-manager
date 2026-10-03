"""Protect original release-check startup, resume and accepted checkpoint ordering."""

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from functools import partialmethod
from pathlib import Path
from typing import Protocol
from typing import Self
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import release_check as legacy
from spotify_manager.routines import scrobble_history
from tests.support.history_dependencies import LegacyReleaseOpening
from tests.support.history_dependencies import release_history


STAMP = datetime(2026, 9, 25, tzinfo=UTC)
ARTIST = legacy.RankedArtist("artist", "Artist", 100, 1)
RUN_ID = "20260925T000000000000Z"


class OpeningObservedError(RuntimeError):
    """Stop the original runner at an explicitly observed opening boundary."""


class OpeningClock(datetime):
    """Keep all original state and audit timestamps deterministic."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Return the fixed original timestamp in the requested timezone.

        Args:
            tz: Original requested timezone.

        Returns:
            Deterministic original timestamp.
        """
        return cls(2026, 9, 25, tzinfo=UTC).astimezone(tz)


def _history(empty: bool) -> scrobble_history.ScrobbleHistorySummary:
    plays = (
        ()
        if empty
        else tuple(Scrobble("Song", "Artist", "Album", index) for index in range(100))
    )
    return scrobble_history.ScrobbleHistorySummary(
        STAMP, "user", plays, len(plays), 0, 2, False, True, None
    )


class EventWriter(Protocol):
    """Original physical event writer signature."""

    def __call__(self, path: Path, run_id: str, event: str, **details: object) -> None:
        """Write an event with its original fields.

        Args:
            path: Audit location.
            run_id: Durable run identity.
            event: Event name.
            details: Event fields in insertion order.
        """


@dataclass
class OpeningEffects:
    """Record original history, accepted file writes, audit and destination progress.

    Args:
        save_original: Original physical state writer.
        audit_original: Original physical event writer.
        empty_history: Supply no eligible plays.
        failure: Boundary at which to stop after recording acceptance.
    """

    save_original: Callable[[dict[str, object], Path], None]
    audit_original: EventWriter
    empty_history: bool = False
    failure: str | None = None
    events: list[str] = field(default_factory=list)

    def _record(self, event: str) -> None:
        self.events.append(event)
        if event == self.failure:
            raise OpeningObservedError(event)

    def refresh(
        self, *args: object, **kwargs: object
    ) -> scrobble_history.ScrobbleHistorySummary:
        """Observe original actual history refresh even for release previews.

        Args:
            args: Original caller-owned history client.
            kwargs: Original paths, progress and refresh settings.

        Returns:
            Original refreshed canonical history summary.
        """
        assert kwargs["dry_run"] is False and kwargs["now"] == STAMP
        self._record("refresh")
        callback = kwargs["progress_callback"]
        if callback is not None:
            cast(Callable[[str], None], callback)("history progress")
        return _history(self.empty_history)

    def save(self, state: dict[str, object], path: Path) -> None:
        """Accept the original physical checkpoint before a possible later failure.

        Args:
            state: Original complete state payload.
            path: Original explicit state location.
        """
        self.save_original(state, path)
        self._record("saved")

    def audit(self, path: Path, run_id: str, event: str, **details: object) -> None:
        """Accept original event bytes before a possible later failure.

        Args:
            path: Original audit location.
            run_id: Original durable run identity.
            event: Original event name.
            details: Original event fields in insertion order.
        """
        self.audit_original(path, run_id, event, **details)
        self._record(f"audit:{event}")

    def progress(self, done: int, total: int, text: str) -> None:
        """Stop immediately before the original destination observations.

        Args:
            done: Original completed artist count.
            total: Original ranked artist count.
            text: Original stage message.

        Raises:
            OpeningObservedError: The original opening is complete.
        """
        self._record(f"progress:{done}:{total}:{text}")
        if text == "Loading destination playlists":
            raise OpeningObservedError("opening complete")


def _bind(monkeypatch: pytest.MonkeyPatch, effects: OpeningEffects) -> None:
    monkeypatch.setattr(legacy, "datetime", OpeningClock)
    monkeypatch.setattr(legacy, "save_state", effects.save)
    monkeypatch.setattr(legacy, "append_event", effects.audit)
    monkeypatch.setattr(
        LegacyReleaseOpening, "refresh", partialmethod(release_history, effects.refresh)
    )


def _active() -> dict[str, object]:
    return {
        "run_id": "resumed",
        "started_at": STAMP.isoformat(),
        "checked_from": "2025-12-31",
        "checked_through": "2026-09-01",
        "artists": [asdict(ARTIST)],
        "completed_artist_keys": [],
        "pending_release_id": None,
    }


def _state(profile: str) -> dict[str, object]:
    state = cast(dict[str, object], legacy._default_state())
    state["operator_field"] = {"keep": "original"}
    if profile == "previous":
        state["last_checked_through"] = "2025-12-31"
    if profile == "invalid_previous":
        state["last_checked_through"] = "not a date"
    if profile.startswith("resume"):
        state["active_run"] = _active()
    if profile == "resume_invalid":
        cast(dict[str, object], state["active_run"])["checked_from"] = "invalid"
    return state


def _invoke(tmp_path: Path, preview: bool, effects: OpeningEffects) -> None:
    legacy.run_release_check(
        cast(Spotify, object()),
        cast(legacy.LastFmReader, object()),
        legacy.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="user",
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "audit.jsonl",
        now=STAMP,
        dry_run=preview,
        progress_callback=effects.progress,
    )


@pytest.mark.parametrize(
    "profile",
    [
        "cold",
        "previous",
        "preview",
        "empty",
        "invalid_previous",
        "resume",
        "resume_invalid",
    ],
)
def test_original_release_opening(
    profile: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Protect preview refresh, resume windows and accepted opening artifacts.

    Args:
        profile: Original opening scenario.
        monkeypatch: Original outer-boundary substitutions.
        tmp_path: Isolated state and audit locations.
    """
    state = _state(profile)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    effects = OpeningEffects(legacy.save_state, legacy.append_event, profile == "empty")
    _bind(monkeypatch, effects)
    with pytest.raises((OpeningObservedError, legacy.ReleaseCheckError)):
        _invoke(tmp_path, profile == "preview", effects)
    actual = json.loads(state_path.read_text())
    assert actual["operator_field"] == state["operator_field"]
    _assert_opening(profile, effects, actual, state, tmp_path / "audit.jsonl")


def _assert_opening(
    profile: str,
    effects: OpeningEffects,
    actual: dict[str, object],
    original: dict[str, object],
    audit: Path,
) -> None:
    refresh = ["refresh", "progress:0:0:history progress"]
    if profile in {"empty", "invalid_previous", "resume_invalid"}:
        assert effects.events == ([] if profile.startswith("resume") else refresh)
        assert actual == original and not audit.exists()
        return
    if profile in {"preview", "resume"}:
        assert effects.events == (refresh if profile == "preview" else []) + [
            "progress:0:1:Loading destination playlists"
        ]
        assert actual == original and not audit.exists()
        return
    assert effects.events == refresh + [
        "saved",
        "audit:run_started",
        "progress:0:1:Loading destination playlists",
    ]
    active = cast(dict[str, object], actual["active_run"])
    expected_start = "2025-12-31" if profile == "previous" else "2026-01-01"
    assert (
        active["checked_from"] == expected_start
        and active["checked_through"] == "2026-09-25"
    )
    assert active["artists"] == [asdict(ARTIST)] and active["run_id"] == RUN_ID
    assert actual["updated_at"] == STAMP.isoformat()
    event = json.loads(audit.read_text())
    assert event == {
        "recorded_at": STAMP.isoformat(),
        "run_id": RUN_ID,
        "event": "run_started",
        "checked_from": expected_start,
        "checked_through": "2026-09-25",
        "artists": 1,
    }


@pytest.mark.parametrize("failure", ["saved", "audit:run_started"])
def test_original_release_opening_accepted_failure(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retain accepted initial checkpoints when audit or later opening work fails.

    Args:
        failure: Original accepted boundary after which to fail.
        monkeypatch: Original outer-boundary substitutions.
        tmp_path: Isolated state and audit locations.
    """
    effects = OpeningEffects(legacy.save_state, legacy.append_event, failure=failure)
    _bind(monkeypatch, effects)
    with pytest.raises(OpeningObservedError, match=failure):
        _invoke(tmp_path, False, effects)
    assert (
        json.loads((tmp_path / "state.json").read_text())["active_run"]["run_id"]
        == RUN_ID
    )
    assert (tmp_path / "audit.jsonl").exists() is (failure == "audit:run_started")
    assert effects.events == ["refresh", "progress:0:0:history progress", "saved"] + (
        ["audit:run_started"] if failure == "audit:run_started" else []
    )
