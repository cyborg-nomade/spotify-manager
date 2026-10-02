"""Independent Found Art refresh, preview, accepted append and audit coordination."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.found_art_values import FoundArtSummary
from spotify_manager.application.recommendation_run import RecommendationRun
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


STAMP = datetime(2026, 7, 22, tzinfo=UTC)
WEEK = date(2026, 7, 17)
PLAY = Scrobble("Seed", "Artist", "Album", 1000)
SEED = FoundArtSeed("Artist", "Seed", ("artist", "seed"), "recent", 1, 1, 1)
CANDIDATE = FoundArtCandidate("New", "Track", ("new", "track"), 1, 1, ())
MATCH = SpotifyTrackMatch("id", "uri", "Track", ("New",), "Album", 1, 1, None, 50)


@dataclass
class RunMemory:
    """Track accepted effects and original parameter forwarding without runtime IO.

    Args:
        failure: Optional recorded boundary to fail.
        total: Observed destination size.
        matches: Configured pending additions.
        events: Ordered workflow boundaries.
        messages: Original visible progress.
        previews: Original history refresh preview requests.
        requests: Resolved addition counts.
        pools: Original minimum or scaled pool limits.
        summaries: Accepted audit summaries.
    """

    failure: str = ""
    total: int = 2
    matches: tuple[SpotifyTrackMatch, ...] = (MATCH,)
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    previews: list[bool] = field(default_factory=list)
    requests: list[int] = field(default_factory=list)
    pools: list[int] = field(default_factory=list)
    summaries: list[FoundArtSummary] = field(default_factory=list)

    def _step(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def clock(self) -> datetime:
        """Resolve effective UTC time after request validation.

        Returns:
            Original effective run timestamp.
        """
        self._step("clock")
        return STAMP

    def week(self, stamp: datetime) -> date:
        """Resolve the effective calendar once per run.

        Args:
            stamp: Original effective UTC timestamp.

        Returns:
            Original listening week's Friday.
        """
        assert stamp is STAMP
        self._step("week")
        return WEEK

    def refresh(
        self, generated_at: datetime, dry_run: bool
    ) -> tuple[list[Scrobble], int]:
        """Accept canonical history refresh before destination reads.

        Args:
            generated_at: Original effective UTC timestamp.
            dry_run: Original preview mode.

        Returns:
            One canonical play and original live-added count.
        """
        assert generated_at is STAMP
        self.previews.append(dry_run)
        self._step("history")
        return [PLAY], 3

    def read(self) -> PlaylistState:
        """Read destination capacity after canonical history.

        Returns:
            Configured original destination size and empty membership.
        """
        self._step("playlist")
        return PlaylistState(self.total, frozenset())

    def seeds(
        self, history: tuple[TrackHistory, ...], count: int, week: date
    ) -> tuple[FoundArtSeed, ...]:
        """Select from aggregated canonical history after checking destination capacity.

        Args:
            history: Original aggregated canonical plays.
            count: Original requested seed count.
            week: Original listening week.

        Returns:
            One configured original seed.
        """
        assert count == len(history) == 1 and week == WEEK
        assert history[0].key == ("artist", "seed")
        self._step("seeds")
        return (SEED,)

    def gather(
        self,
        seeds: tuple[FoundArtSeed, ...],
        heard: set[TrackKey],
        week: date,
        pool_size: int,
        generated_at: datetime,
    ) -> tuple[FoundArtCandidate, ...]:
        """Observe original neighborhood and checkpoint parameters.

        Args:
            seeds: Original ordered selected seeds.
            heard: Original heard identities.
            week: Original effective listening week.
            pool_size: Original minimum or scaled pool limit.
            generated_at: Original effective UTC timestamp.

        Returns:
            One configured original ranked candidate.
        """
        assert seeds == (SEED,) and heard == {("artist", "seed")}
        assert week == WEEK and generated_at is STAMP
        self.pools.append(pool_size)
        self._step("gather")
        return (CANDIDATE,)

    def resolve(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        playlist: PlaylistState,
        count: int,
        dry_run: bool,
    ) -> tuple[tuple[FoundArtResult, ...], tuple[SpotifyTrackMatch, ...]]:
        """Resolve original catalog observations after cache gathering.

        Args:
            candidates: Original ranked pool.
            playlist: Original destination observation.
            count: Resolved requested additions.
            dry_run: Original presentation mode.

        Returns:
            Configured ordered outcomes and pending additions.
        """
        assert candidates == (CANDIDATE,) and playlist.total_items == self.total
        self.requests.append(count)
        self._step("resolve")
        if not self.matches:
            return (FoundArtResult(CANDIDATE, None, "no Spotify match"),), ()
        return (
            FoundArtResult(CANDIDATE, MATCH, "would add" if dry_run else "added"),
        ), self.matches

    def append(self, pending: list[SpotifyTrackMatch]) -> None:
        """Accept ordered remote additions before the audit boundary.

        Args:
            pending: Original pending matches in selection order.
        """
        assert pending == list(self.matches)
        self._step("append")

    def audit(self, summary: FoundArtSummary) -> None:
        """Observe completed audit acceptance after effects or preview selection.

        Args:
            summary: Original completed result.
        """
        self.summaries.append(summary)
        self._step("audit")

    def progress(self, message: str) -> None:
        """Present original playlist and append progress at their original boundaries.

        Args:
            message: Original presentation text.
        """
        self.messages.append(message)
        self._step("adding" if message.startswith("Adding") else "loading")

    def workflow(self) -> RecommendationRun:
        """Compose an independent coordinator with deterministic calendar callbacks.

        Returns:
            Injected recommendation coordinator.
        """
        return RecommendationRun(self, self.clock, self.week, self.progress)


def _run(memory: RunMemory, dry_run: bool = False) -> FoundArtSummary:
    return memory.workflow().run("destination", 1, None, 1, dry_run)


@pytest.mark.parametrize("dry_run", [False, True])
def test_preview_retains_all_observations_and_audit_except_remote_append(
    dry_run: bool,
) -> None:
    """Preserve original action counts and projected lengths in real and preview runs.

    Args:
        dry_run: Original preview request.
    """
    memory = RunMemory()
    summary = _run(memory, dry_run)
    assert memory.events == [
        "clock",
        "week",
        "history",
        "loading",
        "playlist",
        "seeds",
        "gather",
        "resolve",
    ] + ([] if dry_run else ["adding", "append"]) + ["audit"]
    assert memory.previews == [dry_run] and memory.requests == [1]
    assert memory.pools == [100] and memory.summaries == [summary]
    assert summary.generated_at == STAMP and summary.week_start == WEEK
    assert summary.playlist_id == "destination"
    assert (
        summary.history_tracks
        == summary.history_scrobbles
        == summary.seed_count
        == summary.candidate_count
        == 1
    )
    assert summary.live_scrobbles_added == 3 and summary.requested_count == 1
    assert summary.playlist_length_before == 2 and summary.playlist_length_after == (
        2 if dry_run else 3
    )
    assert summary.added == (0 if dry_run else 1) and summary.selected == 1
    assert summary.seeds == (SEED,)


@pytest.mark.parametrize(
    "failure",
    [
        "clock",
        "week",
        "history",
        "loading",
        "playlist",
        "seeds",
        "gather",
        "resolve",
        "adding",
        "append",
        "audit",
    ],
)
def test_failure_retains_only_accepted_effect_prefix(failure: str) -> None:
    """Stop at each original boundary, including progress and accepted remote append.

    Args:
        failure: Recorded operation to fail.
    """
    memory = RunMemory(failure=failure)
    with pytest.raises(OSError, match=failure):
        _run(memory)
    order = [
        "clock",
        "week",
        "history",
        "loading",
        "playlist",
        "seeds",
        "gather",
        "resolve",
        "adding",
        "append",
        "audit",
    ]
    assert memory.events == order[: order.index(failure) + 1]
    assert len(memory.summaries) == (1 if failure == "audit" else 0)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("maximum", [1, 2])
def test_full_destination_retains_history_and_empty_completed_audit(
    dry_run: bool, maximum: int
) -> None:
    """Capacity and over-capacity destinations still refresh history and audit.

    Args:
        dry_run: Original preview mode.
        maximum: Destination capacity at or below observed size.
    """
    memory = RunMemory()
    summary = memory.workflow().run("destination", None, maximum, 1, dry_run)
    assert memory.events == ["clock", "week", "history", "loading", "playlist", "audit"]
    assert (
        summary.requested_count
        == summary.seed_count
        == summary.candidate_count
        == summary.selected
        == summary.added
        == 0
    )
    assert summary.playlist_length_before == summary.playlist_length_after == 2
    assert summary.history_tracks == summary.history_scrobbles == 1
    assert summary.live_scrobbles_added == 3
    assert summary.seeds == ()
    assert summary.results == ()
    assert memory.summaries == [summary] and memory.previews == [dry_run]


@pytest.mark.parametrize(
    "count,maximum,requested,pool",
    [
        (None, None, 20, 200),
        (None, 32, 30, 300),
        (1, None, 1, 100),
    ],
)
def test_resolved_request_and_original_pool_floor_scale(
    count: int | None,
    maximum: int | None,
    requested: int,
    pool: int,
) -> None:
    """Retain explicit, default and capacity request calculations.

    Args:
        count: Optional explicit additions.
        maximum: Optional destination capacity.
        requested: Expected original addition count.
        pool: Expected original candidate limit.
    """
    memory = RunMemory()
    summary = memory.workflow().run("destination", count, maximum, 1, False)
    assert memory.requests == [requested] and memory.pools == [pool]
    assert summary.requested_count == requested


@pytest.mark.parametrize(
    "count,maximum,seeds,message",
    [
        (1, 1, 1, "Use either"),
        (0, None, 1, "Count"),
        (-1, None, 1, "Count"),
        (None, 0, 1, "Maximum"),
        (None, -1, 1, "Maximum"),
        (1, None, 0, "Seed"),
        (None, None, -1, "Seed"),
    ],
)
def test_invalid_request_precedes_clock_and_all_observations(
    count: int | None,
    maximum: int | None,
    seeds: int,
    message: str,
) -> None:
    """Retain validation order before any calendar, history or playlist observation.

    Args:
        count: Original optional explicit request.
        maximum: Original optional capacity.
        seeds: Original requested seed count.
        message: Original validation error prefix.
    """
    memory = RunMemory()
    with pytest.raises(FoundArtConfigError, match=message):
        memory.workflow().run("destination", count, maximum, seeds, False)
    assert memory.events == []


def test_empty_pending_keeps_audit_without_adding_message_or_append() -> None:
    """Unresolved recommendations still report and audit their complete observations."""
    memory = RunMemory(matches=())
    summary = _run(memory)
    assert summary.results == (FoundArtResult(CANDIDATE, None, "no Spotify match"),)
    assert summary.added == summary.selected == 0
    assert summary.playlist_length_after == 2
    assert memory.messages == ["Loading the Found Art Spotify playlist"]
    assert "append" not in memory.events and memory.events[-1] == "audit"


def test_existing_configuration_values_are_injected_without_new_defaults() -> None:
    """Bind mutable outer limits rather than silently hard-code application defaults."""
    memory = RunMemory()
    workflow = RecommendationRun(
        memory, memory.clock, memory.week, memory.progress, 7, 2, 3
    )
    summary = workflow.run("destination", None, None, 1, False)
    assert summary.requested_count == 7 and memory.pools == [21]
