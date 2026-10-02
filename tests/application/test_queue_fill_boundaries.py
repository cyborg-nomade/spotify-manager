"""Protect Queue fill guards, no-capacity exits and candidate stopping boundaries."""

from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.queue_fill import QueueFill
from spotify_manager.application.queue_fill_values import QueueFillRequest
from spotify_manager.application.queue_values import QueueConfigError
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed
from tests.support.queue_fill import ARTIST
from tests.support.queue_fill import RECOMMENDATION
from tests.support.queue_fill import FillObservations
from tests.support.queue_fill_application import MemoryQueueFill


@dataclass
class BoundaryFill(MemoryQueueFill):
    """Expose opening and bounded-pool observations with caller-supplied facts.

    Args:
        observations: Original accepted-effect recorder.
        length: Original observed Queue length.
        pool: Original ordered candidate facts.
    """

    length: int = 0
    pool: tuple[ArtistRecommendation, ...] = (RECOMMENDATION, RECOMMENDATION)

    def configure(self) -> None:
        """Observe retry configuration after request validation."""
        self.observations.record("configure")

    def queue_length(self) -> int:
        """Observe Queue membership and return configured capacity facts.

        Returns:
            Configured original Queue length.
        """
        super().queue_length()
        return self.length

    def candidates(
        self,
        seeds: tuple[ArtistSeed, ...],
        heard: set[str],
        week: date,
        limit: int,
        now: datetime,
    ) -> tuple[ArtistRecommendation, ...]:
        """Observe gathering before returning the configured candidate pool.

        Args:
            seeds: Original ordered seeds.
            heard: Original heard identities.
            week: Original effective week.
            limit: Original pool size.
            now: Original effective time.

        Returns:
            Configured original ordered candidates.
        """
        super().candidates(seeds, heard, week, limit, now)
        return self.pool


@pytest.mark.parametrize(
    "fill_request,message",
    [
        (
            QueueFillRequest(1, 1, 30, False),
            "Use either count or maximum playlist length, not both.",
        ),
        (QueueFillRequest(0, None, 30, False), "Count must be at least 1."),
        (
            QueueFillRequest(None, 0, 30, False),
            "Maximum playlist length must be at least 1.",
        ),
    ],
)
def test_fill_validation_precedes_retry_and_all_reads(
    fill_request: QueueFillRequest,
    message: str,
) -> None:
    """Reject original invalid limits before dependency observations.

    Args:
        fill_request: Original conflicting or invalid limits.
        message: Original error text.
    """
    observations = FillObservations("success")
    with pytest.raises(QueueConfigError) as error:
        QueueFill(BoundaryFill(observations)).run(fill_request)
    assert str(error.value) == message
    assert observations.trace == []


@pytest.mark.parametrize("preview", [False, True])
def test_full_queue_stops_after_history_and_initial_membership(preview: bool) -> None:
    """Avoid seeds, candidate cache, representations and state when capacity is zero.

    Args:
        preview: Original preview mode.
    """
    observations = FillObservations("success")
    result = QueueFill(BoundaryFill(observations, length=2)).run(
        QueueFillRequest(None, 1, 30, preview)
    )
    assert result.requested_count == result.selected == 0
    assert result.playlist_length_before == result.playlist_length_after == 2
    assert result.seed_count == result.candidate_count == 0
    assert result.results == ()
    assert [row[0] for row in observations.trace] == [
        "configure",
        "history",
        "progress",
        "playlist",
    ]


def test_requested_addition_stops_before_next_candidate_progress() -> None:
    """Stop once the original requested additions are satisfied."""
    observations = FillObservations("success")
    result = QueueFill(BoundaryFill(observations)).run(
        QueueFillRequest(1, None, 30, False)
    )
    assert result.selected == 1
    assert len(result.results) == 1
    assert sum(row[0] == "top" for row in observations.trace) == 1
    assert [row for row in observations.trace if row[0] == "progress"] == [
        ["progress", 0, 0, "history status"],
        ["progress", 0, 2, "Resolving Artist"],
    ]


def test_saved_mapping_skips_interaction_and_duplicate_artist_is_rejected() -> None:
    """Reuse accepted mappings and representation updates within the original run."""
    observations = FillObservations("success")
    observations.state["artist_mappings"] = {"artist": asdict(ARTIST)}
    result = QueueFill(BoundaryFill(observations)).run(
        QueueFillRequest(2, None, 30, False)
    )
    assert result.selected == 1
    assert [row.action for row in result.results] == ["added", "already represented"]
    assert not observations.checkpoints
    assert not any(row[0] == "resolve" for row in observations.trace)


def test_default_count_retains_original_twenty() -> None:
    """Preserve the original default when neither count nor maximum is specified."""
    observations = FillObservations("skip")
    result = QueueFill(BoundaryFill(observations)).run(
        QueueFillRequest(None, None, 30, False)
    )
    assert result.requested_count == 20
    assert result.candidate_count == 2
