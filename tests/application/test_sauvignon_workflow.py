"""Exercise Sauvignon with independent history, choice, append and audit boundaries."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Literal
from typing import cast

import pytest

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.application.sauvignon_run import SauvignonRun
from spotify_manager.application.sauvignon_run import SauvignonStages
from spotify_manager.application.sauvignon_selection import AlbumEditionChoice
from spotify_manager.application.sauvignon_values import SauvignonConfigError
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_selection import PendingAlbum
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
from tests.support.runtime_resources import ProgressMessages
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

    def prepare(self) -> None:
        """Keep the scripted invocation's existing retry authority."""

    def append(self, additions: list[PendingAlbum]) -> None:
        """Record accepted proposals before their possible ambiguous failure.

        Args:
            additions: Original ordered pending marker pairs.
        """
        self.accepted.extend(track.uri for _album, track in additions)
        self.record("append")

    def local_date(self, value: datetime | date | None = None) -> date:
        """Return the original scripted local date for the calendar boundary."""
        return WEEK

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


@dataclass(frozen=True)
class _ScriptedSeeds:
    """Supply a scripted child-stage outcome at its original boundary.

    Args:
        source: Existing observations, scripted results and failures.
    """

    source: Effects

    def run(
        self, history: tuple[TrackHistory, ...], count: int, week: date
    ) -> tuple[FoundArtSeed, ...]:
        """Return the existing scripted result and retain its observations."""
        return self.source.seeds(history, count, week)


@dataclass(frozen=True)
class _ScriptedTracks:
    """Supply a scripted child-stage outcome at its original boundary.

    Args:
        source: Existing observations, scripted results and failures.
    """

    source: Effects

    def run(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[tuple[str, str]],
        week: date,
        pool: int,
        now: datetime,
    ) -> tuple[FoundArtCandidate, ...]:
        """Return the existing scripted result and retain its observations."""
        return self.source.tracks(seeds, heard, week, pool, now)


@dataclass(frozen=True)
class _ScriptedAlbums:
    """Supply a scripted child-stage outcome at its original boundary.

    Args:
        source: Existing observations, scripted results and failures.
    """

    source: Effects

    def run(
        self,
        tracks: tuple[FoundArtCandidate, ...],
        excluded: set[tuple[str, str]],
        existing: set[str],
        maximum: int,
        week: date,
    ) -> tuple[AlbumRecommendation, ...]:
        """Return the existing scripted result and retain its observations."""
        return self.source.albums(tracks, excluded, existing, maximum, week)


def _stages(effects: Effects) -> SauvignonStages:
    return SauvignonStages(
        cast(RecommendationSeeds, _ScriptedSeeds(effects)),
        cast(CandidateGathering, _ScriptedTracks(effects)),
        cast(AlbumGathering, _ScriptedAlbums(effects)),
        cast(AlbumEditionChoice, effects),
    )


def _workflow(effects: Effects) -> SauvignonRun:
    return SauvignonRun(
        effects,
        _stages(effects),
        ClockResource(),
        effects,
        ProgressMessages(effects),
        effects,
    )


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


class ClockResource:
    """Own the original fixed fixture observation."""

    def now(self) -> datetime:
        """Observe the original fixture boundary.

        Returns:
            Original fixture response.
        """
        return _clock()
