"""Original Found Art run ordering, previews and accepted mutation boundaries."""

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import found_art
from tests.routines.test_found_art import FakeLastFm
from tests.routines.test_found_art import candidate
from tests.routines.test_found_art import seed


STAMP = datetime(2026, 7, 22, tzinfo=UTC)
WEEK = date(2026, 7, 17)
MATCH = blast.SpotifyTrackMatch(
    "id", "uri", "Track", ("Artist",), "Album", 1, 1, None, 50
)


@dataclass
class RunSteps:
    """Observe accepted run boundaries without external clients or durable files.

    Args:
        failure: Optional boundary to fail after recording acceptance.
        total: Observed destination size.
        events: Ordered workflow boundaries.
        summaries: Accepted audit summaries.
        previews: History refresh preview modes.
        requested: Resolved addition counts.
    """

    failure: str = ""
    total: int = 2
    events: list[str] = field(default_factory=list)
    summaries: list[found_art.FoundArtSummary] = field(default_factory=list)
    previews: list[bool] = field(default_factory=list)
    requested: list[int] = field(default_factory=list)

    def _step(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def history(
        self,
        lastfm: found_art.LastFmReader,
        *,
        export_path: Path,
        recent_path: Path,
        dry_run: bool,
        now: datetime,
        progress_callback: found_art.ProgressCallback | None,
    ) -> tuple[list[blast.Scrobble], int]:
        """Accept the original history refresh before any playlist read.

        Args:
            lastfm: Caller-owned history source.
            export_path: Original export path.
            recent_path: Original delta path.
            dry_run: Original preview mode.
            now: Resolved UTC timestamp.
            progress_callback: Original progress observer.

        Returns:
            One canonical play and the live-added count.
        """
        assert now == STAMP
        self.previews.append(dry_run)
        self._step("history")
        return [blast.Scrobble("Seed", "Artist", "Album", 1000)], 3

    def read(self, sp: Spotify, playlist_id: str) -> blast.PlaylistState:
        """Observe the destination after history refresh.

        Args:
            sp: Caller-owned client.
            playlist_id: Original destination.

        Returns:
            Configured destination size and empty membership.
        """
        self._step("playlist")
        return blast.PlaylistState(self.total, frozenset())

    def seeds(
        self,
        history: Iterable[found_art.TrackHistory],
        *,
        seed_count: int,
        week_start: date,
    ) -> tuple[found_art.FoundArtSeed, ...]:
        """Select seeds after destination capacity is known.

        Args:
            history: Aggregated original canonical plays.
            seed_count: Original request.
            week_start: Original effective week.

        Returns:
            One configured recommendation seed.
        """
        assert len(tuple(history)) == seed_count == 1
        assert week_start == WEEK
        self._step("seeds")
        return (seed("Artist", "Seed"),)

    def gather(
        self,
        lastfm: found_art.LastFmReader,
        seeds: tuple[found_art.FoundArtSeed, ...],
        heard_keys: set[found_art.TrackKey],
        *,
        cache_path: Path,
        log_path: Path,
        week_start: date,
        candidate_pool_size: int,
        now: datetime,
        progress_callback: found_art.ProgressCallback | None,
    ) -> tuple[found_art.FoundArtCandidate, ...]:
        """Observe neighborhoods and cache handling in both real and preview runs.

        Args:
            lastfm: Original neighborhood source.
            seeds: Ordered selected seeds.
            heard_keys: Aggregated heard identities.
            cache_path: Original cache destination.
            log_path: Original prior-addition log.
            week_start: Original listening week.
            candidate_pool_size: Original minimum or scaled pool.
            now: Original effective UTC timestamp.
            progress_callback: Original progress observer.

        Returns:
            One configured candidate.
        """
        assert heard_keys == {("artist", "seed")}
        assert week_start == WEEK and now == STAMP
        assert candidate_pool_size >= 100
        self._step("gather")
        return (candidate("New", "Track", 1),)

    def resolve(
        self,
        sp: Spotify,
        candidates: tuple[found_art.FoundArtCandidate, ...],
        playlist: blast.PlaylistState,
        *,
        count: int,
        dry_run: bool,
        progress_callback: found_art.ProgressCallback | None,
    ) -> tuple[
        tuple[found_art.FoundArtResult, ...], tuple[blast.SpotifyTrackMatch, ...]
    ]:
        """Resolve after cache observations and before append.

        Args:
            sp: Original client.
            candidates: Original ordered pool.
            playlist: Original membership.
            count: Resolved addition count.
            dry_run: Original preview mode.
            progress_callback: Original progress observer.

        Returns:
            One selected match and its original action.
        """
        self.requested.append(count)
        self._step("resolve")
        action: found_art.FoundArtAction = "would add" if dry_run else "added"
        return (found_art.FoundArtResult(candidates[0], MATCH, action),), (MATCH,)

    def append(
        self, sp: Spotify, playlist_id: str, matches: list[blast.SpotifyTrackMatch]
    ) -> None:
        """Record remote acceptance before the audit boundary.

        Args:
            sp: Original client.
            playlist_id: Original destination.
            matches: Original ordered pending additions.
        """
        assert matches == [MATCH]
        self._step("append")

    def audit(self, summary: found_art.FoundArtSummary, path: Path) -> None:
        """Record the audit after accepted appends or preview selection.

        Args:
            summary: Original completed result.
            path: Original log destination.
        """
        self.summaries.append(summary)
        self._step("audit")


def _install(steps: RunSteps, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(found_art, "refresh_scrobble_history", steps.history)
    monkeypatch.setattr(blast, "load_playlist_state", steps.read)
    monkeypatch.setattr(found_art, "select_seed_tracks", steps.seeds)
    monkeypatch.setattr(found_art, "gather_candidates", steps.gather)
    monkeypatch.setattr(found_art, "resolve_spotify_candidates", steps.resolve)
    monkeypatch.setattr(blast, "add_spotify_matches", steps.append)
    monkeypatch.setattr(found_art, "append_found_art_log", steps.audit)


def _run(
    count: int | None = 1,
    maximum: int | None = None,
    dry_run: bool = False,
    progress: found_art.ProgressCallback | None = None,
) -> found_art.FoundArtSummary:
    return found_art.run_found_art(
        cast(Spotify, object()),
        FakeLastFm(),
        "destination",
        count=count,
        max_playlist_length=maximum,
        seed_count=1,
        dry_run=dry_run,
        now=STAMP,
        progress_callback=progress,
    )


@pytest.mark.parametrize(
    "failure", ["history", "playlist", "seeds", "gather", "resolve", "append", "audit"]
)
def test_failure_stops_after_original_accepted_boundary(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Later observations and audit do not proceed after the failed boundary.

    Args:
        monkeypatch: Isolated original boundary patches.
        failure: Original boundary to fail.
    """
    steps = RunSteps(failure=failure)
    _install(steps, monkeypatch)
    with pytest.raises(OSError, match=failure):
        _run()
    order = ["history", "playlist", "seeds", "gather", "resolve", "append", "audit"]
    assert steps.events == order[: order.index(failure) + 1]
    assert len(steps.summaries) == (1 if failure == "audit" else 0)


@pytest.mark.parametrize("dry_run", [False, True])
def test_preview_retains_history_gathering_resolution_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    """Only remote append and adding progress are suppressed by preview mode.

    Args:
        monkeypatch: Isolated original boundary patches.
        dry_run: Original preview request.
    """
    steps = RunSteps()
    _install(steps, monkeypatch)
    messages: list[str] = []
    summary = _run(dry_run=dry_run, progress=messages.append)
    assert steps.events == ["history", "playlist", "seeds", "gather", "resolve"] + (
        [] if dry_run else ["append"]
    ) + ["audit"]
    assert steps.previews == [dry_run]
    assert summary.playlist_length_after == (2 if dry_run else 3)
    assert summary.added == (0 if dry_run else 1) and summary.selected == 1
    assert (
        summary.history_tracks
        == summary.history_scrobbles
        == summary.candidate_count
        == summary.seed_count
        == 1
    )
    assert summary.live_scrobbles_added == 3
    assert messages == ["Loading the Found Art Spotify playlist"] + (
        [] if dry_run else ["Adding 1 tracks to Found Art"]
    )
    assert steps.summaries == [summary]


@pytest.mark.parametrize("dry_run", [False, True])
def test_full_destination_still_refreshes_history_and_audits(
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    """Capacity checks occur after history and retain the empty completed audit.

    Args:
        monkeypatch: Isolated original boundary patches.
        dry_run: Original preview request.
    """
    steps = RunSteps()
    _install(steps, monkeypatch)
    summary = _run(count=None, maximum=2, dry_run=dry_run)
    assert steps.events == ["history", "playlist", "audit"]
    assert summary.requested_count == summary.seed_count == summary.candidate_count == 0
    assert summary.seeds == ()
    assert summary.results == ()
    assert summary.playlist_length_before == summary.playlist_length_after == 2
    assert summary.live_scrobbles_added == 3


def test_omitted_count_and_maximum_retain_default_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly absent request settings retain the existing twenty-track fallback.

    Args:
        monkeypatch: Isolated original boundary patches.
    """
    steps = RunSteps()
    _install(steps, monkeypatch)
    summary = _run(count=None)
    assert steps.requested == [20]
    assert summary.requested_count == 20
