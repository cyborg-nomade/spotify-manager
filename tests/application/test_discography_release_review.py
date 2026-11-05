"""Editable artist checklists retain exact editions and recoverable link outcomes."""

from dataclasses import replace

import pytest

from spotify_manager.application.discography_review import DiscographyReleaseReview
from spotify_manager.application.discography_values import DiscographyAlbumError
from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.ports.discography_review import ReleaseReviewSubmission
from spotify_manager.domain.discography_values import QueueArtist
from tests.support.discography_review import FIRST
from tests.support.discography_review import SECOND
from tests.support.discography_review import THIRD
from tests.support.discography_review import ReviewMemory
from tests.support.discography_review import linked
from tests.support.discography_run import release


ARTIST = QueueArtist("artist", "Artist", "newfoundland")


async def test_batch_add_retains_edits_and_exact_chronological_options() -> None:
    """An unchecked original stays unchecked while explicit links are selected."""
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission(
                "add",
                (),
                (f"spotify:album:{FIRST}", f"https://open.spotify.com/album/{SECOND}"),
            )
        ],
        {
            FIRST: linked(FIRST, "Recent", "2020"),
            SECOND: linked(SECOND, "Earlier", "1990"),
        },
    )
    result = await DiscographyReleaseReview(memory, memory).run(
        ARTIST, (release("old"),)
    )
    assert [entry.spotify_id for entry in result] == [SECOND, FIRST]
    assert memory.requested == [FIRST, SECOND]
    assert memory.drafts[-1].selected_ids == (FIRST, SECOND)
    assert len(memory.drafts[-1].entries) == 3
    assert memory.drafts[-1].entries[0].artists == ("Other Artist", "Guest Artist")


async def test_repeated_ids_reuse_options_and_do_not_repeat_spotify_reads() -> None:
    """Duplicate URLs and URIs select the same row once, including a fetched row."""
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission(
                "add", (), (FIRST, f"spotify:album:{SECOND}", SECOND)
            ),
        ],
        {SECOND: linked(SECOND)},
    )
    result = await DiscographyReleaseReview(memory, memory).run(
        ARTIST, (release(FIRST),)
    )
    assert {entry.spotify_id for entry in result} == {FIRST, SECOND}
    assert len(result) == 2 and memory.requested == [SECOND]
    assert "Already listed" in memory.drafts[-1].notices[-1]


async def test_bad_and_unavailable_links_do_not_discard_valid_additions() -> None:
    """Each reference has feedback and a later valid addition still becomes usable."""
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("add", (), ("not-a-link", FIRST, SECOND)),
        ],
        {FIRST: DiscographyAlbumError("Unavailable"), SECOND: linked(SECOND)},
    )
    result = await DiscographyReleaseReview(memory, memory).run(ARTIST, ())
    assert [entry.spotify_id for entry in result] == [SECOND]
    notices = memory.drafts[-1].notices
    assert len(notices) == 3 and "Unavailable" in notices[1]
    assert memory.requested == [FIRST, SECOND]


async def test_explicit_alternate_edition_is_not_replaced_by_canonical_preference() -> (
    None
):
    """A linked edition survives the presence of a preferred saved edition."""
    original = replace(release(FIRST), saved=True, identity="same")
    alternate = replace(
        linked(SECOND), release=replace(linked(SECOND).release, identity="same")
    )
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("add", (FIRST,), (SECOND,)),
            ReleaseReviewSubmission("select", (SECOND,)),
        ],
        {SECOND: alternate},
    )
    result = await DiscographyReleaseReview(memory, memory).run(ARTIST, (original,))
    assert result == (alternate.release,)
    assert len(memory.drafts[-1].entries) == 2


async def test_invalid_selection_retains_draft_for_another_decision() -> None:
    """Unknown IDs cannot enter a plan or cause repeated metadata reads."""
    memory = ReviewMemory(
        [
            ReleaseReviewSubmission("select", (THIRD,)),
            ReleaseReviewSubmission("select", (FIRST,)),
        ]
    )
    result = await DiscographyReleaseReview(memory, memory).run(
        ARTIST, (release(FIRST),)
    )
    assert result == (release(FIRST),)
    assert memory.drafts[-1].notices == ("Selected releases are not available.",)


@pytest.mark.parametrize("choice", ["none", "quit"])
async def test_decline_and_cancel_do_not_apply_unconfirmed_additions(
    choice: str,
) -> None:
    """Ending review produces an explicit decline or cancellation with no writes.

    Args:
        choice: Operator's decline or quit control.
    """
    answer = (
        ReleaseReviewSubmission("none")
        if choice == "none"
        else ReleaseReviewSubmission("quit")
    )
    memory = ReviewMemory(
        [ReleaseReviewSubmission("add", (), (FIRST,)), answer], {FIRST: linked(FIRST)}
    )
    stage = DiscographyReleaseReview(memory, memory)
    if choice == "quit":
        with pytest.raises(DiscographyCancelledError):
            await stage.run(ARTIST, ())
        return
    assert await stage.run(ARTIST, ()) == ()


@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
async def test_cancellation_guards_each_read_only_review_boundary(
    boundary: int,
) -> None:
    """Cancellation can stop before prompts, additions and post-read publication.

    Args:
        boundary: Check before/after interaction, before lookup or after lookup.
    """
    memory = ReviewMemory(
        [ReleaseReviewSubmission("add", (), (FIRST,))],
        {FIRST: linked(FIRST)},
        interrupt_at=boundary,
    )
    with pytest.raises(RuntimeError, match="review cancelled"):
        await DiscographyReleaseReview(memory, memory).run(ARTIST, ())
    assert len(memory.requested) == (1 if boundary == 4 else 0)


async def test_transport_failure_is_not_mislabelled_as_a_missing_album() -> None:
    """Only a named recoverable album error returns feedback to the draft."""
    memory = ReviewMemory(
        [ReleaseReviewSubmission("add", (), (FIRST,))],
        {FIRST: RuntimeError("transport")},
    )
    with pytest.raises(RuntimeError, match="transport"):
        await DiscographyReleaseReview(memory, memory).run(ARTIST, ())
