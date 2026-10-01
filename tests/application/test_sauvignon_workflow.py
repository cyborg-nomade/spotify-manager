"""Exercise Sauvignon with independent history, choice, append and audit boundaries."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Literal

import pytest

from spotify_manager.application.sauvignon_run import SauvignonRun
from spotify_manager.application.sauvignon_values import SauvignonConfigError
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_selection import PendingAlbum
from tests.support.sauvignon_run import STAMP
from tests.support.sauvignon_run import WEEK
from tests.support.sauvignon_run import RunObservations
from tests.support.sauvignon_run import marker
from tests.support.sauvignon_run import recommendation


@dataclass
class Effects(RunObservations):
    """Accept original ordered proposals with explicit ambiguous-write failure.

    Args:
        failure: Optional boundary to fail after recording acceptance.
    """

    def append(self, additions: list[PendingAlbum]) -> None:
        """Record accepted proposals before their possible ambiguous failure.

        Args:
            additions: Original ordered pending marker pairs.
        """
        self.accepted.extend(track.uri for _album, track in additions)
        self.record("append")

    def choose(
        self, item: AlbumRecommendation, *args: object
    ) -> SpotifyAlbumOption | Literal["skip", "quit"]:
        """Return original configured controls or the first edition.

        Args:
            item: Original evidence.

        Returns:
            Chosen edition or control response.
        """
        self.record(f"choose:{item.album}")
        choice = self.choices.get(item.album)
        if choice == "skip":
            return "skip"
        if choice == "quit":
            return "quit"
        return item.options[0]


def _clock() -> datetime:
    return STAMP


def _week(stamp: datetime) -> date:
    return WEEK


def _workflow(effects: Effects) -> SauvignonRun:
    return SauvignonRun(effects, _clock, _week, effects.progress, effects.echo)


EVENTS = [
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


@pytest.mark.parametrize("failure", EVENTS)
def test_sauvignon_failure_prefix(failure: str) -> None:
    """Protect every observed stage and accepted write before later failure.

    Args:
        failure: Original failure boundary.
    """
    effects = Effects(
        failure=failure,
        recommendations=(recommendation(), recommendation("two", "Other")),
    )
    with pytest.raises(RuntimeError, match=failure):
        _workflow(effects).run("destination", 2, None, 30, False)
    assert effects.events == EVENTS[: EVENTS.index(failure) + 1]
    expected = (
        ["spotify:track:one", "spotify:track:two"]
        if EVENTS.index(failure) >= EVENTS.index("append")
        else []
    )
    assert effects.accepted == expected


@pytest.mark.parametrize("dry_run", [False, True])
def test_sauvignon_completed_run(dry_run: bool) -> None:
    """Protect original preview counts, audit and requested selection limit.

    Args:
        dry_run: Original preview mode.
    """
    effects = Effects(
        recommendations=(recommendation(), recommendation("two", "Other"))
    )
    summary = _workflow(effects).run("destination", 1, None, 30, dry_run)
    assert summary.selected == 1
    assert summary.playlist_length_after == (0 if dry_run else 1)
    assert summary.live_scrobbles_added == 2
    assert effects.summary == summary
    assert "choose:two" not in effects.events


def test_sauvignon_fresh_membership() -> None:
    """Protect album and track duplicate filtering and initial-size projection."""
    effects = Effects(
        initial=(marker("initial"),),
        current=(marker("one"), marker("other", "track-two")),
        recommendations=(recommendation(), recommendation("two", "Other")),
    )
    summary = _workflow(effects).run("destination", 2, None, 30, False)
    assert [result.action for result in summary.results] == ["already represented"] * 2
    assert summary.selected == 0
    assert summary.playlist_length_after == 1
    assert effects.accepted == []
    assert effects.events[-2:] == ["read:2", "audit"]


@pytest.mark.parametrize(
    "choice,action,paused", [("skip", "skipped", False), ("quit", "quit", True)]
)
def test_sauvignon_controls(choice: str, action: str, paused: bool) -> None:
    """Protect skip continuation and immediate quit before later observations.

    Args:
        choice: Original control.
        action: Original resulting outcome.
        paused: Original summary pause state.
    """
    effects = Effects(
        recommendations=(recommendation(), recommendation("two", "Other")),
        choices={"one": choice},
    )
    summary = _workflow(effects).run("destination", 3, None, 30, False)
    assert summary.results[0].action == action
    assert summary.paused is paused
    assert ("choose:two" in effects.events) is not paused


def test_sauvignon_artist_and_album_uniqueness() -> None:
    """Protect artist suppression before choice and album suppression before loading."""
    effects = Effects(
        recommendations=(
            recommendation(),
            recommendation("two"),
            recommendation("one", "Other"),
        )
    )
    summary = _workflow(effects).run("destination", 3, None, 30, True)
    assert [result.action for result in summary.results] == [
        "would add",
        "artist already selected",
        "already represented",
    ]
    assert effects.events.count("first:one") == 1
    assert "choose:two" not in effects.events


@pytest.mark.parametrize("maximum", [None, 20, 5])
def test_sauvignon_capacity(maximum: int | None) -> None:
    """Retain history refresh and audit when explicit or fallback capacity is full.

    Args:
        maximum: Original explicit or fallback capacity.
    """
    effects = Effects(initial=(marker("existing"),) * 20)
    summary = _workflow(effects).run("destination", None, maximum, 30, False)
    assert summary.requested_count == 0
    assert effects.events == EVENTS[:3] + ["audit"]


@pytest.mark.parametrize(
    "count,maximum,seeds", [(1, 20, 30), (0, None, 30), (None, 0, 30), (None, 20, 0)]
)
def test_sauvignon_validation(
    count: int | None, maximum: int | None, seeds: int
) -> None:
    """Reject original invalid requests before time and external observations.

    Args:
        count: Original addition count.
        maximum: Original capacity.
        seeds: Original seed count.
    """
    effects = Effects()
    with pytest.raises(SauvignonConfigError):
        _workflow(effects).run("destination", count, maximum, seeds, False)
    assert effects.events == []
