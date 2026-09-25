"""Album retention rules over already-observed liked-track counts."""

from dataclasses import dataclass
from math import floor
from typing import Literal


type AlbumDecision = Literal["keep", "remove"]


@dataclass(frozen=True)
class AlbumAssessment:
    """An album decision without transport or presentation metadata.

    Args:
        required_liked_tracks: Minimum liked count under the legacy floor rule.
        liked_ratio: Liked fraction, or zero for an empty album.
        decision: Whether the observed count meets the required count.
    """

    required_liked_tracks: int
    liked_ratio: float
    decision: AlbumDecision


def required_liked_tracks(total_tracks: int, threshold: float) -> int:
    """Calculate the legacy minimum, including empty and nonpositive inputs.

    Args:
        total_tracks: Observed album size.
        threshold: Required proportion; values outside zero to one remain valid.

    Returns:
        One for empty albums, zero for nonpositive thresholds, otherwise a floor.

    Raises:
        ValueError: A positive-size album has a NaN threshold.
        OverflowError: A positive-size album has an infinite positive threshold.
    """
    if total_tracks <= 0:
        return 1
    if threshold <= 0:
        return 0
    return max(1, floor(total_tracks * threshold))


def assess_album(
    total_tracks: int, liked_tracks: int, threshold: float
) -> AlbumAssessment:
    """Decide retention using observed counts without imposing new validation.

    Args:
        total_tracks: Observed album size.
        liked_tracks: Number of liked tracks.
        threshold: Required proportion of liked tracks.

    Returns:
        The required count, observed ratio, and keep/remove decision.

    Raises:
        ValueError: The threshold calculation receives NaN.
        OverflowError: The threshold calculation receives positive infinity.
    """
    required = required_liked_tracks(total_tracks, threshold)
    ratio = liked_tracks / total_tracks if total_tracks else 0.0
    decision: AlbumDecision = "keep" if liked_tracks >= required else "remove"
    return AlbumAssessment(required, ratio, decision)
