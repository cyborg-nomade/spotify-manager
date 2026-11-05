"""Preserve default-count eligibility while packing explicit additions in full."""

from dataclasses import replace

import pytest

from spotify_manager.application.discography_planning import DiscographyPlanning
from spotify_manager.application.discography_review import DiscographyReleaseReview
from spotify_manager.application.ports.discography_review import ReleaseReviewSubmission
from spotify_manager.domain.discography_values import QueueArtist
from tests.support.discography_review import FIRST
from tests.support.discography_review import SECOND
from tests.support.discography_review import ReviewMemory
from tests.support.discography_review import linked
from tests.support.discography_run import PlanReads
from tests.support.discography_run import release
from tests.support.discography_run import scripted_reads


def _planner(memory: ReviewMemory) -> DiscographyPlanning:
    reads = scripted_reads(PlanReads("normal", "newfoundland"))
    return DiscographyPlanning(
        replace(reads, review=DiscographyReleaseReview(memory, memory))
    )


def _ids(prefix: str, count: int) -> tuple[str, ...]:
    return tuple(f"{prefix}-{index}" for index in range(count))


async def test_seven_default_records_are_not_prompted_for_two_free_slots() -> None:
    """Only an eligible filler is reviewed after the initial eight records."""
    memory = ReviewMemory()
    planner = _planner(memory)
    planner.catalogs["a"] = tuple(release(identity) for identity in _ids("a", 8))
    planner.catalogs["b"] = tuple(release(identity) for identity in _ids("b", 7))
    planner.catalogs["c"] = tuple(release(identity) for identity in _ids("c", 2))
    plan = await planner.run()
    assert [draft.artist.name for draft in memory.drafts] == ["Alpha", "Gamma"]
    assert [draft.remaining for draft in memory.drafts] == [None, 2]
    assert [artist.spotify_id for artist in plan.artists] == ["a", "c"]
    assert (plan.total_releases, plan.days, plan.open_slots) == (10, 5, 0)


async def test_first_artist_additions_update_capacity_before_default_filter() -> None:
    """First-artist additions are counted before choosing eligible fillers."""
    original = _ids("a", 4)
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("add", original, (FIRST, SECOND)),
            ReleaseReviewSubmission("select", (*original, FIRST, SECOND)),
        ],
        {FIRST: linked(FIRST), SECOND: linked(SECOND)},
    )
    plan = await _planner(memory).run()
    assert [artist.spotify_id for artist in plan.artists] == ["a", "d"]
    assert [artist.release_count for artist in plan.artists] == [6, 2]
    assert (plan.total_releases, plan.days, plan.open_slots) == (8, 4, 2)
    assert memory.drafts[-1].remaining == 4


@pytest.mark.parametrize("optional_only", [False, True])
async def test_zero_default_filler_is_not_offered(optional_only: bool) -> None:
    """Empty and optional-only fillers retain the previous eligibility rule.

    Args:
        optional_only: Whether the catalogue contains one non-default live record.
    """
    memory = ReviewMemory()
    planner = _planner(memory)
    planner.catalogs["b"] = (release("live", False),) if optional_only else ()
    plan = await planner.run()
    assert [draft.artist.name for draft in memory.drafts] == ["Alpha", "Gamma"]
    assert [artist.spotify_id for artist in plan.artists] == ["a", "c"]
    assert plan.total_releases == 10 and memory.requested == []


@pytest.mark.parametrize("count,expected", [(1, True), (2, True), (7, False)])
async def test_eligibility_reads_defaults_without_prompting(
    count: int, expected: bool
) -> None:
    """Capacity checks remain independent of operator edits.

    Args:
        count: Fetched default release count.
        expected: Whether that catalogue is eligible for the two free slots.
    """
    memory = ReviewMemory()
    planner = _planner(memory)
    planner.catalogs["b"] = tuple(release(identity) for identity in _ids("b", count))
    assert await planner._fits(QueueArtist("b", "Beta", "memory_lane"), 2) is expected
    assert memory.drafts == []


@pytest.mark.parametrize("additions,total", [(3, 20), (13, 30)])
async def test_eligible_filler_additions_extend_the_target_multiple(
    additions: int, total: int
) -> None:
    """Keep all accepted additions and reconsider artists against new capacity.

    Args:
        additions: Extra records added to an eligible two-record filler.
        total: Next complete multiple reached after the additions.
    """
    extra = tuple(character * 22 for character in "mnopqrstuvwxy"[:additions])
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("select", _ids("a", 8)),
            ReleaseReviewSubmission("add", _ids("c", 2), extra),
            ReleaseReviewSubmission("select", (*_ids("c", 2), *extra)),
            ReleaseReviewSubmission("none"),
            ReleaseReviewSubmission("select", _ids("b", 7)),
        ]
    )
    for identity in extra:
        memory.albums[identity] = linked(identity)
    planner = _planner(memory)
    for artist, count in (("a", 8), ("b", 7), ("c", 2)):
        identities = _ids(artist, count)
        planner.catalogs[artist] = tuple(release(identity) for identity in identities)
    plan = await planner.run()
    assert [artist.spotify_id for artist in plan.artists] == ["a", "c", "b"]
    assert (plan.total_releases, plan.days, plan.open_slots) == (total, total / 2, 0)
    assert memory.drafts[1].remaining == 2 and memory.drafts[-1].remaining == 7
    assert memory.requested == list(extra)
