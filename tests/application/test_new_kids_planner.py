"""Discovery planning preserves observations, choices and historical audit order."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace

import pytest

from spotify_manager.application.composer_routes import ChoiceCandidate
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.new_kids_planner import ReviewDecision
from spotify_manager.application.new_kids_planner import ReviewSource
from spotify_manager.application.new_kids_values import FlushResult
from spotify_manager.application.new_kids_values import NewKidsError
from tests.support.discovery_memory import MemoryDiscovery
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
CURRENT = release("album")
OTHER = release("other")


def _memory() -> MemoryDiscovery:
    return MemoryDiscovery(
        catalogs={"artist": (CURRENT, OTHER)},
        releases={"album": (track("source"),), "other": (track("next"),)},
    )


def _planner(memory: MemoryDiscovery, *, preview: bool = False) -> NewKidsPlanner:
    observations = DiscoveryObservations(memory, {})
    return NewKidsPlanner(observations, memory.choose, memory, memory, 2026, preview)


def _context(
    planner: NewKidsPlanner, *, prior: object = None, index: int | None = 0
) -> ReviewSource:
    observations = planner.observations
    catalog = observations.catalog("artist")
    tracks = observations.tracks(CURRENT)
    return ReviewSource(
        SOURCE,
        "artist",
        "Artist",
        {"prior_unliked_streak": prior},
        catalog,
        CURRENT,
        tracks,
        tracks,
        index,
    )


def _plan(decision: ReviewDecision) -> dict[str, object]:
    assert isinstance(decision, dict)
    return decision


def test_next_release_plan_audits_history_before_requesting_a_choice() -> None:
    """Completion checks all current tracks before candidate reads and interaction."""
    memory = _memory()
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner)))
    assert plan["action"] == "next_release" and plan["release_number"] == 1
    assert plan["target"] == asdict(track("next"))
    assert [name for name, value in memory.events] == [
        "catalog",
        "tracks",
        "memberships",
        "memberships",
        "memberships",
        "message",
        "audit",
        "tracks",
        "choice",
    ]
    assert memory.events[6] == (
        "audit",
        (
            "annual_release_progress_checked",
            {
                "artist": "Artist",
                "artist_id": "artist",
                "year": 2026,
                "played_release_ids": [],
                "played_release_names": [],
                "dry_run": False,
            },
        ),
    )


@pytest.mark.parametrize("liked", [False, True])
def test_intra_release_advance_uses_observed_streak_without_history(
    liked: bool,
) -> None:
    """Normal advancement does not read other releases or emit completion events.

    Args:
        liked: Current source membership.
    """
    memory = _memory()
    memory.releases["album"] = (track("source"), track("next"))
    memory.liked_statuses["source"] = liked
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, prior=True)))
    assert plan["action"] == "advance" and plan["advance_reason"] == "next track"
    assert (
        plan["consecutive_unliked"]
        == plan["next_prior_unliked_streak"]
        == (0 if liked else 2)
    )
    assert [name for name, value in memory.events] == [
        "catalog",
        "tracks",
        "memberships",
    ]


def test_missing_saved_streak_is_reconstructed_from_preceding_primary_tracks() -> None:
    """Observe the source before predecessors and reset the streak on a live like."""
    memory = _memory()
    memory.releases["album"] = (
        track("liked"),
        track("before"),
        track("source"),
        track("next"),
    )
    memory.liked_statuses["liked"] = True
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, prior="invalid", index=2)))
    assert plan["consecutive_unliked"] == 2
    assert memory.events[2:4] == [
        ("memberships", ["source"]),
        ("memberships", ["liked", "before"]),
    ]


def test_three_unlikes_advance_to_later_like_and_reset_persisted_streak() -> None:
    """The later-liked shortcut observes all primary tracks before choosing a target."""
    memory = _memory()
    memory.releases["album"] = (track("source"), track("unliked"), track("liked"))
    memory.liked_statuses["liked"] = True
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, prior=2)))
    assert plan["advance_reason"] == "next liked track"
    assert (
        plan["target"] == asdict(track("liked"))
        and plan["next_prior_unliked_streak"] == 0
    )
    assert "audit" not in [name for name, value in memory.events]


def test_unmapped_source_uses_zero_prior_and_proceeds_to_release_completion() -> None:
    """An unmapped source does not infer predecessors or advance within the release."""
    memory = _memory()
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, index=None)))
    assert plan["consecutive_unliked"] == 1 and plan["action"] == "next_release"
    assert ("memberships", []) not in memory.events


@pytest.mark.parametrize("choice", ["__skip__", "__quit__", "missing"])
def test_release_choice_controls_preserve_prior_history_audit(choice: str) -> None:
    """Pause, skip and selection errors all follow the existing preview audit.

    Args:
        choice: Operator control or unsupported release response.
    """
    memory = _memory()
    memory.choices = [choice]
    planner = _planner(memory, preview=True)
    context = _context(planner)
    if choice == "missing":
        with pytest.raises(NewKidsError, match="Selected release"):
            planner.plan(context)
    else:
        decision = planner.plan(context)
        assert (
            decision is None
            if choice == "__quit__"
            else isinstance(decision, FlushResult)
        )
    assert [name for name, value in memory.events][-3:] == ["audit", "tracks", "choice"]
    assert context.progress == {"prior_unliked_streak": None}


@pytest.mark.parametrize(
    "qualified,top,action",
    [
        (True, False, "unfollowed"),
        (True, True, "great discovery"),
        (False, True, "unlucky"),
    ],
)
def test_exhausted_catalog_routes_from_live_assessment(
    qualified: bool, top: bool, action: str
) -> None:
    """No viable next release triggers live completion with the original precedence.

    Args:
        qualified: Whether all catalog albums are saved.
        top: Whether Spotify supplies a liked top track.
        action: Existing expected terminal result.
    """
    memory = _memory()
    memory.catalogs["artist"] = (CURRENT,)
    memory.albums = {"album": qualified}
    memory.top = (track("top"),) if top else ()
    memory.liked_statuses["top"] = top
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, prior=2)))
    assert (plan["action"], plan["result_action"]) == ("finish", action)
    assert plan["target"] is None and "assessment" in plan
    assert "choice" not in [name for name, value in memory.events]


def test_completed_release_limit_bypasses_viable_candidate_observations() -> None:
    """Sufficient annual completion triggers assessment before candidate selection."""
    memory = _memory()
    planner = _planner(memory)
    planner.observations.release_limit = 1
    planner.observations.studio_minimum = 1
    planner.observations.history = {("artist", "album"): frozenset({"source"})}
    plan = _plan(planner.plan(_context(planner)))
    assert plan["action"] == "finish"
    assert ("message", ("Artist", 1, 2026)) in memory.events
    assert "choice" not in [name for name, value in memory.events]


def test_candidate_scan_reads_all_remaining_releases_before_limiting_display() -> None:
    """Viability uses primary credits and preserves the ten-choice display cap."""
    memory = _memory()
    releases = tuple(release(str(index)) for index in range(11))
    fallback = replace(release("fallback"), tier=1)
    guest = release("guest")
    memory.catalogs["artist"] = (CURRENT, guest, fallback, *releases)
    memory.releases["guest"] = (replace(track("guest"), primary_artist_id="guest"),)
    memory.releases["fallback"] = (track("fallback"),)
    for candidate in releases:
        memory.releases[candidate.spotify_id] = (track(candidate.spotify_id),)
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner)))
    assert plan["target_release"] == asdict(releases[0])
    assert ("tracks", "10") in memory.events and ("tracks", "guest") in memory.events
    assert memory.events[-1] == ("choice", ("Artist", releases[:10]))


def test_completed_and_current_release_identities_are_excluded_from_choices() -> None:
    """Exclude alternative editions and historically completed release identities."""
    memory = _memory()
    played = release("played")
    edition = replace(release("edition"), identity=CURRENT.identity)
    memory.catalogs["artist"] = (CURRENT, edition, played, OTHER)
    memory.releases["played"] = (track("one"), track("two"), track("three"))
    planner = _planner(memory)
    planner.observations.history = {
        ("artist", "played"): frozenset({"one", "two", "three"})
    }
    plan = _plan(planner.plan(_context(planner)))
    assert plan["release_number"] == 2 and plan["target_release"] == asdict(OTHER)
    assert memory.events[-1] == ("choice", ("Artist", (OTHER,)))
    assert ("tracks", "edition") not in memory.events


@dataclass
class ChangedTracks:
    """Simulate a callback changing shared observations before final selection.

    Args:
        observations: Planner cache whose selected candidate becomes unavailable.
    """

    observations: DiscoveryObservations

    def choose(self, artist: str, candidates: tuple[ChoiceCandidate, ...]) -> str:
        """Accept the candidate after its previously viable tracks disappear.

        Args:
            artist: Logical display name.
            candidates: Offered candidates.

        Returns:
            Originally viable candidate identifier.
        """
        self.observations.release_tracks["other"] = ()
        return "other"


def test_selected_release_without_primary_tracks_retains_original_error() -> None:
    """Selection rechecks its shared accepted tracks before creating a durable plan."""
    memory = _memory()
    planner = _planner(memory)
    changed = ChangedTracks(planner.observations)
    planner = replace(planner, choose=changed.choose)
    with pytest.raises(NewKidsError, match="no primary-artist tracks"):
        planner.plan(_context(planner))


def test_observations_cache_empty_catalogs_and_works_without_refresh() -> None:
    """Empty accepted responses remain stable throughout one invocation."""
    memory = MemoryDiscovery()
    observations = DiscoveryObservations(memory, {})
    assert observations.catalog("missing") == observations.catalog("missing") == ()
    assert (
        observations.composer_tracks("works")
        == observations.composer_tracks("works")
        == ()
    )
    assert observations.tracks(CURRENT) == observations.tracks(CURRENT) == ()
    assert memory.events == [
        ("catalog", "missing"),
        ("playlist", "works"),
        ("tracks", "album"),
    ]


def test_empty_current_release_still_observes_source_before_next_release_choice() -> (
    None
):
    """Empty catalog tracks do not suppress the original live source observation."""
    memory = _memory()
    memory.releases["album"] = ()
    planner = _planner(memory)
    plan = _plan(planner.plan(_context(planner, index=None)))
    assert plan["action"] == "next_release"
    assert memory.events[2:4] == [("memberships", ["source"]), ("memberships", [])]
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, dict) and evaluation["total_tracks"] == 0
