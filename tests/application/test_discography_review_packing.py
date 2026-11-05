"""Reviewed selections determine weekly packing before any default-size shortcut."""

from dataclasses import replace

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


async def test_oversized_defaults_are_reviewed_and_reduced_before_fitting() -> None:
    """Beta's eight defaults cannot hide a six-release operator selection."""
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("select", ("a-0", "a-1", "a-2", "a-3")),
            ReleaseReviewSubmission(
                "select", ("b-0", "b-1", "b-2", "b-3", "b-4", "b-5")
            ),
        ]
    )
    plan = await _planner(memory).run()
    assert [artist.spotify_id for artist in plan.artists] == ["a", "b"]
    assert [artist.release_count for artist in plan.artists] == [4, 6]
    assert (plan.total_releases, plan.days, plan.open_slots) == (10, 5, 0)
    assert [draft.remaining for draft in memory.drafts] == [None, 6]


async def test_added_releases_change_counts_days_and_following_artist_capacity() -> (
    None
):
    """Two linked editions increase Alpha to six and leave four slots for Beta."""
    original = ("a-0", "a-1", "a-2", "a-3")
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("add", original, (FIRST, SECOND)),
            ReleaseReviewSubmission("select", (*original, FIRST, SECOND)),
            ReleaseReviewSubmission("select", ("b-0", "b-1", "b-2", "b-3")),
        ],
        {FIRST: linked(FIRST), SECOND: linked(SECOND)},
    )
    plan = await _planner(memory).run()
    assert [artist.release_count for artist in plan.artists] == [6, 4]
    assert plan.total_releases == 10 and plan.open_slots == 0
    assert memory.drafts[-1].remaining == 4
    assert {item.spotify_id for item in plan.artists[0].releases} == set(
        (*original, FIRST, SECOND)
    )


async def test_empty_catalog_can_be_filled_by_links_instead_of_silently_skipped() -> (
    None
):
    """A zero-default candidate still has an editable checklist before packing."""
    ids = tuple(character * 22 for character in "abcdef")
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("select", ("a-0", "a-1", "a-2", "a-3")),
            ReleaseReviewSubmission("add", (), ids),
        ],
    )
    for identity in ids:
        memory.albums[identity] = linked(identity)
    planner = _planner(memory)
    planner.catalogs["b"] = ()
    plan = await planner.run()
    assert [artist.spotify_id for artist in plan.artists] == ["a", "b"]
    assert plan.total_releases == 10 and plan.open_slots == 0
    assert memory.drafts[1].entries == ()
    assert memory.requested == list(ids)


async def test_nondefault_selection_and_its_cached_count_override_default_count() -> (
    None
):
    """A live-only fetched option can be explicitly chosen despite zero defaults."""
    memory = ReviewMemory([ReleaseReviewSubmission("select", ("live",))])
    planner = _planner(memory)
    planner.catalogs["b"] = (release("live", False),)
    candidate = QueueArtist("b", "Beta", "memory_lane")
    assert await planner._fits(candidate, 1)
    assert await planner._fits(candidate, 1)
    assert len(memory.drafts) == 1


async def test_actual_oversized_selection_is_not_packed_into_remaining_slots() -> None:
    """Reviewing a candidate cannot override the weekly packing boundary."""
    memory = ReviewMemory()
    plan = await _planner(memory).run()
    assert [draft.artist.name for draft in memory.drafts] == ["Alpha", "Beta", "Gamma"]
    assert [artist.spotify_id for artist in plan.artists] == ["a", "c"]
    assert plan.total_releases == 10 and plan.open_slots == 0
