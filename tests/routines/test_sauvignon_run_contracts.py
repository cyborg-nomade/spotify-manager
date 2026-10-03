"""Protect original Sauvignon stage order, accepted writes and fresh membership."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.infrastructure.legacy.sauvignon import LegacySauvignon
from spotify_manager.routines import sauvignon as legacy
from tests.support.sauvignon_run import STAMP
from tests.support.sauvignon_run import RunObservations
from tests.support.sauvignon_run import marker
from tests.support.sauvignon_run import recommendation


class RunSpotify:
    """Accept additions before recording an injected remote failure.

    Args:
        observations: Shared ordered effect record.
    """

    def __init__(self, observations: RunObservations) -> None:
        self.observations = observations

    def _post(self, endpoint: str, payload: dict[str, list[str]]) -> None:
        """Record an accepted append before its possible ambiguous failure.

        Args:
            endpoint: Original endpoint.
            payload: Original ordered URI payload.
        """
        assert endpoint == "playlists/destination/items"
        self.observations.accepted.extend(payload["uris"])
        self.observations.record("append")


def _first(
    observations: RunObservations,
    sp: object,
    album: legacy.SpotifyAlbumOption,
    retry: object,
) -> legacy.FirstTrack:
    return observations.first(album)


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


def _bind(monkeypatch: pytest.MonkeyPatch, observations: RunObservations) -> None:
    monkeypatch.setattr(LegacySauvignon, "refresh", observations.refresh)
    monkeypatch.setattr(LegacySauvignon, "seeds", observations.seeds)
    monkeypatch.setattr(LegacySauvignon, "tracks", observations.tracks)
    monkeypatch.setattr(LegacySauvignon, "read", observations.read)
    monkeypatch.setattr(LegacySauvignon, "previous", observations.previous)
    monkeypatch.setattr(LegacySauvignon, "albums", observations.albums)
    monkeypatch.setattr(LegacySauvignon, "choose", observations.choose)
    monkeypatch.setattr(LegacySauvignon, "first", observations.first)
    monkeypatch.setattr(LegacySauvignon, "audit", observations.audit)


def _run(
    observations: RunObservations,
    tmp_path: Path,
    dry_run: bool = False,
    count: int | None = 2,
) -> legacy.SauvignonSummary:
    return legacy.fill_sauvignon_from_lastfm(
        cast(Spotify, RunSpotify(observations)),
        cast(legacy.LastFmReader, object()),
        "destination",
        None,
        count=count,
        max_playlist_length=None,
        now=STAMP,
        log_path=tmp_path / "audit",
        dry_run=dry_run,
        echo=observations.echo,
        progress_callback=observations.progress,
        retry_call=_immediate,
    )


SUCCESS = [
    "refresh",
    "progress:Loading Sauvignon Terre-Neuve",
    "read:1",
    "seeds",
    "tracks",
    "previous",
    "albums",
    "choose:one",
    "first:one",
    "choose:two",
    "first:two",
    "progress:Rechecking Sauvignon before adding albums",
    "read:2",
    "append",
    "echo:Added 2 albums to Sauvignon Terre-Neuve.",
    "audit",
]


@pytest.mark.parametrize("failure", SUCCESS)
def test_original_failure_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    """Protect every original failure prefix and remotely accepted additions."""
    observations = RunObservations(
        failure=failure,
        recommendations=(recommendation(), recommendation("two", "Other")),
    )
    _bind(monkeypatch, observations)
    with pytest.raises(RuntimeError, match=failure):
        _run(observations, tmp_path)
    assert observations.events == SUCCESS[: SUCCESS.index(failure) + 1]
    accepted = (
        ["spotify:track:one", "spotify:track:two"]
        if SUCCESS.index(failure) >= SUCCESS.index("append")
        else []
    )
    assert observations.accepted == accepted


def test_original_fresh_recheck_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retain original album/track suppression and initial-size projection."""
    observations = RunObservations(
        initial=(marker("initial"),),
        current=(marker("one"), marker("unrelated", "track-two"), marker("third")),
        recommendations=(recommendation(), recommendation("two", "Other")),
    )
    _bind(monkeypatch, observations)
    summary = _run(observations, tmp_path)
    assert observations.accepted == []
    assert [result.action for result in summary.results] == ["already represented"] * 2
    assert summary.playlist_length_before == summary.playlist_length_after == 1
    assert summary.selected == 0
    assert observations.events[-2:] == ["read:2", "audit"]


def test_original_preview_still_audits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retain original preview audit after proposals without a remote append."""
    observations = RunObservations(
        recommendations=(recommendation(), recommendation("two", "Other"))
    )
    _bind(monkeypatch, observations)
    summary = _run(observations, tmp_path, True)
    assert observations.events == SUCCESS[:11] + ["audit"]
    assert observations.accepted == []
    assert summary.selected == 2
    assert summary.playlist_length_after == 0
    assert summary.live_scrobbles_added == 2


def test_original_capacity_still_refreshes_and_audits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Retain refresh and audit effects when destination capacity is full."""
    observations = RunObservations(initial=(marker("existing"),) * 20)
    _bind(monkeypatch, observations)
    summary = _run(observations, tmp_path, count=None)
    assert observations.events == SUCCESS[:3] + ["audit"]
    assert summary.requested_count == 0
    assert summary.history_albums == summary.history_scrobbles == 1


@pytest.mark.parametrize(
    "choice,action,paused", [("skip", "skipped", False), ("quit", "quit", True)]
)
def test_original_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    choice: str,
    action: str,
    paused: bool,
) -> None:
    """Retain original skip and quit outcomes before any playable-track read."""
    observations = RunObservations(
        recommendations=(recommendation(),), choices={"one": choice}
    )
    _bind(monkeypatch, observations)
    summary = _run(observations, tmp_path)
    assert [result.action for result in summary.results] == [action]
    assert summary.paused is paused
    assert observations.events == SUCCESS[:8] + ["audit"]


class FalseyRetry:
    """Record configuration evaluation without allowing the ignored retry to run.

    Args:
        events: Original ordered boundary record.
    """

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __bool__(self) -> bool:
        """Record the original falsey retry configuration evaluation.

        Returns:
            Original falsey callable value.
        """
        self.events.append("retry:boolean")
        return False

    def __call__(self, operation: Callable[[], object], description: str) -> object:
        """Reject use of the retry suppressed by the original falsey fallback.

        Args:
            operation: Original operation.
            description: Original retry description.

        Raises:
            AssertionError: The falsey retry must never execute.
        """
        raise AssertionError("falsey retry was invoked")


def test_sauvignon_invalid_request_precedes_retry_configuration(tmp_path: Path) -> None:
    """Preserve original validation before evaluating a supplied falsey retry callable.

    Args:
        tmp_path: Isolated unused audit location.
    """
    events: list[str] = []
    with pytest.raises(legacy.SauvignonConfigError):
        legacy.fill_sauvignon_from_lastfm(
            cast(Spotify, object()),
            cast(legacy.LastFmReader, object()),
            "destination",
            None,
            count=0,
            max_playlist_length=None,
            retry_call=FalseyRetry(events),
            log_path=tmp_path / "audit",
            now=STAMP,
        )
    assert events == []


def test_sauvignon_falsey_retry_is_resolved_before_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retain original falsey retry fallback exactly once before history refresh.

    Args:
        monkeypatch: Original boundary substitutions.
        tmp_path: Isolated unused audit location.
    """
    observed = RunObservations()
    _bind(monkeypatch, observed)
    legacy.fill_sauvignon_from_lastfm(
        cast(Spotify, RunSpotify(observed)),
        cast(legacy.LastFmReader, object()),
        "destination",
        None,
        count=1,
        max_playlist_length=None,
        retry_call=FalseyRetry(observed.events),
        dry_run=True,
        now=STAMP,
        log_path=tmp_path / "audit",
        progress_callback=observed.progress,
    )
    assert observed.events == ["retry:boolean"] + SUCCESS[:7] + ["audit"]
