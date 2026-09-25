"""Decision tables for retention, completion, and artist promotion."""

from dataclasses import FrozenInstanceError

import pytest

from spotify_manager.domain.albums import AlbumAssessment
from spotify_manager.domain.albums import assess_album
from spotify_manager.domain.albums import required_liked_tracks
from spotify_manager.domain.artists import ArtistFacts
from spotify_manager.domain.artists import PromotionReason
from spotify_manager.domain.artists import promotion_reasons
from spotify_manager.domain.completion import release_completed
from spotify_manager.domain.completion import scrobble_threshold


@pytest.mark.parametrize(
    "total,threshold,required",
    [
        (0, 0.5, 1),
        (-1, 0.5, 1),
        (0, 0, 1),
        (3, -0.1, 0),
        (3, 0, 0),
        (1, 0.5, 1),
        (2, 0.5, 1),
        (3, 0.5, 1),
        (5, 0.5, 2),
        (3, 0.01, 1),
        (10, 0.3, 3),
        (10, 1, 10),
        (10, 1.1, 11),
    ],
)
def test_album_threshold(total: int, threshold: float, required: int) -> None:
    """Preserve floor rounding, the empty-album rule, and tolerant thresholds.

    Args:
        total: Reported album size.
        threshold: Required liked proportion.
        required: Reviewed legacy minimum.
    """
    assert required_liked_tracks(total, threshold) == required


@pytest.mark.parametrize(
    "total,liked,threshold,expected",
    [
        (0, 0, 0.5, AlbumAssessment(1, 0.0, "remove")),
        (3, 1, 0.5, AlbumAssessment(1, 1 / 3, "keep")),
        (5, 1, 0.5, AlbumAssessment(2, 0.2, "remove")),
        (5, 2, 0.5, AlbumAssessment(2, 0.4, "keep")),
        (3, 0, 0, AlbumAssessment(0, 0.0, "keep")),
        (3, 4, 0.5, AlbumAssessment(1, 4 / 3, "keep")),
        (0, 1, 0.5, AlbumAssessment(1, 0.0, "keep")),
    ],
)
def test_album_assessment(
    total: int,
    liked: int,
    threshold: float,
    expected: AlbumAssessment,
) -> None:
    """Return exact decisions and ratios without validating legacy counts away.

    Args:
        total: Observed album size.
        liked: Observed liked count.
        threshold: Requested proportion.
        expected: Complete policy outcome.
    """
    assert assess_album(total, liked, threshold) == expected


@pytest.mark.parametrize(
    "threshold,error", [(float("nan"), ValueError), (float("inf"), OverflowError)]
)
def test_nonfinite_threshold_errors(threshold: float, error: type[Exception]) -> None:
    """Retain numeric errors for nonempty albums without rejecting empty inputs.

    Args:
        threshold: Nonfinite requested proportion.
        error: Existing exception from integer rounding.
    """
    with pytest.raises(error):
        assess_album(3, 1, threshold)
    assert required_liked_tracks(0, threshold) == 1
    assert required_liked_tracks(3, -float("inf")) == 0


@pytest.mark.parametrize(
    "facts,expected",
    [
        (ArtistFacts(17, 20, 2, (False,)), ()),
        (ArtistFacts(18, 20, 2, (False,)), (PromotionReason.LIKED_TRACKS,)),
        (ArtistFacts(1, 20, 3, (False,)), (PromotionReason.SAVED_RELEASES,)),
        (ArtistFacts(1, 20, 1, (True,)), (PromotionReason.ALL_ALBUMS,)),
        (ArtistFacts(1, 1, 0, ()), (PromotionReason.ALL_TRACKS,)),
        (ArtistFacts(0, 0, 0, ()), ()),
        (
            ArtistFacts(0, 20, 3, (True,)),
            (PromotionReason.SAVED_RELEASES, PromotionReason.ALL_ALBUMS),
        ),
        (ArtistFacts(18, 18, 3, (True, True)), tuple(PromotionReason)),
    ],
)
def test_promotion_reasons(
    facts: ArtistFacts, expected: tuple[PromotionReason, ...]
) -> None:
    """Retain independent promotion reasons and their user-visible ordering.

    Args:
        facts: Observed library counts and album statuses.
        expected: Reasons in the original evaluation order.
    """
    assert promotion_reasons(facts) == expected


@pytest.mark.parametrize("tier,expected", [(0, 3), (1, 1), (2, 1), (3, 1), (-1, 1)])
def test_completion_threshold(tier: int, expected: int) -> None:
    """Require three distinct studio tracks but one fallback track.

    Args:
        tier: Parsed release tier.
        expected: Required distinct titles.
    """
    assert scrobble_threshold(tier) == expected
    assert scrobble_threshold(tier, 4) == (4 if tier == 0 else 1)


@pytest.mark.parametrize(
    "played,liked,minimum,expected",
    [
        (set(), set(), 3, False),
        ({"a", "b"}, set(), 3, False),
        ({"a", "b", "c"}, set(), 3, True),
        ({"a", "b", "c"}, {"a"}, 3, True),
        ({"a", "b", "c"}, {"missing"}, 3, False),
        ({"a"}, {"a"}, 1, True),
        ({"a"}, {"a", "b"}, 1, False),
        ({""}, {""}, 1, True),
    ],
)
def test_release_completion(
    played: set[str],
    liked: set[str],
    minimum: int,
    expected: bool,
) -> None:
    """Require both distinct-title coverage and every liked title.

    Args:
        played: Matched normalized scrobble titles.
        liked: Normalized liked titles.
        minimum: Tier-specific required count.
        expected: Existing completion decision.
    """
    assert release_completed(played, liked, minimum) is expected


def test_album_assessment_is_immutable() -> None:
    """Keep an evaluated decision stable after construction."""
    assessment = assess_album(3, 1, 0.5)
    with pytest.raises(FrozenInstanceError):
        assessment.decision = "remove"  # type: ignore[misc]
