"""Explicit album choices retain search order and cancellation boundaries."""

import pytest

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.domain.history import Scrobble
from tests.support.manual_matching import AlbumSearch
from tests.support.manual_matching import CatalogChoices
from tests.support.manual_matching import album_candidate


@pytest.mark.parametrize("answer", ["", "two"])
async def test_album_selection_and_rejection_are_explicit(answer: str) -> None:
    """Accept a chosen result without replacing catalog order or applying a score.

    Args:
        answer: Offered identity or explicit no match.
    """
    albums = (album_candidate("one"), album_candidate("two"))
    choices = CatalogChoices([answer])
    stage = ManualAlbumMatching(AlbumSearch(albums), choices, choices)
    play = Scrobble("", "Unrelated artist", "Unrelated album", 0)
    assert await stage.run(play) == (albums[1] if answer else None)
    assert choices.offered == [(play, ("one", "two"))]


async def test_empty_album_results_require_no_match() -> None:
    """Ask the operator even when the valid search page is empty."""
    choices = CatalogChoices([""])
    assert (
        await ManualAlbumMatching(AlbumSearch(), choices, choices).run(
            Scrobble("", "Artist", "Album", 0)
        )
        is None
    )
    assert choices.offered[0][1] == ()


async def test_unoffered_album_cannot_be_accepted() -> None:
    """Reject an operator resource returning an album outside the offered results."""
    choices = CatalogChoices(["other"])
    with pytest.raises(SpotifyTrackResolutionError, match="not offered"):
        await ManualAlbumMatching(AlbumSearch(), choices, choices).run(
            Scrobble("", "Artist", "Album", 0)
        )


@pytest.mark.parametrize("boundary", [1, 2, 3])
async def test_album_cancellation_precedes_acceptance(boundary: int) -> None:
    """Observe cancellation before search, before prompting and after the decision.

    Args:
        boundary: Checkpoint at which cancellation is requested.
    """
    choices = CatalogChoices([""], cancel_at=boundary)
    with pytest.raises(BlastFromPastCancelledError):
        await ManualAlbumMatching(AlbumSearch(), choices, choices).run(
            Scrobble("", "Artist", "Album", 0)
        )
