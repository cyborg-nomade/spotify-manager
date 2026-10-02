"""Exercise saved-album review decisions with deterministic injected effects."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.album_limits import ReviewCounts
from spotify_manager.application.album_limits import ReviewOutcome
from spotify_manager.application.album_limits import review_albums
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus
from spotify_manager.models.your_library import YourLibraryAlbum


def _album() -> YourLibraryAlbum:
    return YourLibraryAlbum(artist="Artist", album="Album", uri="spotify:album:album")


def _evaluation(decision: str = "remove", known_track: bool = True) -> AlbumEvaluation:
    track = AlbumTrackLikedStatus(
        name="Track",
        uri="spotify:track:track",
        liked=False,
        spotify_id="track" if known_track else None,
    )
    return AlbumEvaluation(
        album_name="Album",
        album_id="album",
        artist_name="Artist",
        total_tracks=1,
        liked_tracks=0,
        required_liked_tracks=1,
        liked_ratio=0.0,
        threshold=0.5,
        decision=decision,
        tracks=[track],
        source="files",
        from_cache=True,
    )


@dataclass
class MemoryReview:
    """Library and interaction fake recording observable business boundaries.

    Args:
        assessment: Supplied track facts and retention assessment.
        action: User action returned by the interaction boundary.
        liked: Live membership count.
        previous: Whether the record has a prior keep decision.
        fail: Boundary at which to interrupt execution.
        empty: Whether the loaded review input is empty.
    """

    assessment: AlbumEvaluation = field(default_factory=_evaluation)
    action: str = "remove"
    liked: int = 1
    previous: bool = False
    fail: str | None = None
    empty: bool = False
    events: list[str] = field(default_factory=list, init=False)
    final: ReviewCounts | None = field(default=None, init=False)

    def _effect(self, name: str) -> None:
        self.events.append(name)
        if name == self.fail:
            raise RuntimeError(name)

    def albums(self) -> list[YourLibraryAlbum]:
        """Read one original album.

        Returns:
            One deterministic album.
        """
        self._effect("load")
        return [] if self.empty else [_album()]

    def previously_kept(self, album: YourLibraryAlbum) -> bool:
        """Read a prior choice.

        Args:
            album: Current item.

        Returns:
            Configured prior decision.
        """
        self._effect("previous")
        return self.previous

    def follow_artist(self, album: YourLibraryAlbum) -> bool:
        """Simulate a completed artist follow.

        Args:
            album: Current item.

        Returns:
            True for a completed new follow.
        """
        self._effect("follow")
        return True

    def evaluate(self, album: YourLibraryAlbum) -> AlbumEvaluation:
        """Read the configured assessment.

        Args:
            album: Current item.

        Returns:
            Configured assessment.
        """
        self._effect("evaluate")
        return self.assessment

    def live_likes(self, album: YourLibraryAlbum, track_ids: list[str]) -> int:
        """Record a live membership read.

        Args:
            album: Current item.
            track_ids: Ordered known identifiers.

        Returns:
            Configured live membership count.
        """
        assert track_ids == ["track"]
        self._effect("live")
        return self.liked

    def show_live_likes(self, count: int | None) -> None:
        """Record live count presentation.

        Args:
            count: Observed count, or None when no identifiers are known.
        """
        self._effect(f"display-live:{count}")

    def remove(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
        *,
        automatic: bool,
    ) -> None:
        """Record a removal and its reason.

        Args:
            album: Current item.
            evaluation: Current assessment.
            live_likes: Last live count.
            automatic: Whether zero live likes caused removal.
        """
        self._effect(f"remove:{automatic}:{live_likes}")

    def keep(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
    ) -> None:
        """Record a persisted keep choice.

        Args:
            album: Current item.
            evaluation: Current assessment.
            live_likes: Last live count.
        """
        self._effect("persist-keep")

    def outcome(
        self,
        outcome: ReviewOutcome,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation | None,
        position: int,
        total: int,
    ) -> None:
        """Record the presented outcome.

        Args:
            outcome: Completed decision or quit.
            album: Current item.
            evaluation: Current assessment when available.
            position: One-based position.
            total: Original input count.
        """
        self._effect(f"outcome:{outcome}")

    def candidate(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        position: int,
        total: int,
    ) -> None:
        """Record candidate presentation.

        Args:
            album: Current item.
            evaluation: Current assessment.
            position: One-based position.
            total: Original input count.
        """
        self._effect("candidate")

    def choose(self, album: YourLibraryAlbum, evaluation: AlbumEvaluation) -> str:
        """Return the configured user choice.

        Args:
            album: Current item.
            evaluation: Current assessment.

        Returns:
            Configured normalized action.
        """
        self._effect("choose")
        return self.action

    def progress(self, position: int, total: int) -> None:
        """Record completion progress.

        Args:
            position: Completed position.
            total: Original input count.
        """
        self._effect(f"progress:{position}/{total}")

    def finish(self, counts: ReviewCounts) -> None:
        """Snapshot the final counts.

        Args:
            counts: Completed outcomes.
        """
        self._effect("finish")
        self.final = counts


@pytest.mark.parametrize(
    "action,outcome,counts",
    [
        ("remove", "removed", ReviewCounts(removed=1, followed=1)),
        ("keep", "kept anyway", ReviewCounts(kept=1, followed=1)),
        ("skip", "skip", ReviewCounts(skipped=1, followed=1)),
        ("quit", "quit", ReviewCounts(followed=1)),
    ],
)
def test_review_choices_keep_effect_order(
    action: str, outcome: str, counts: ReviewCounts
) -> None:
    """Retain live checks, choice effects, and progress after each user action.

    Args:
        action: Scripted normalized choice.
        outcome: Expected displayed outcome.
        counts: Expected completed-work counts.
    """
    fixture = MemoryReview(action=action)
    review_albums(fixture, fixture)
    expected = [
        "load",
        "previous",
        "follow",
        "evaluate",
        "candidate",
        "live",
        "display-live:1",
        "choose",
    ]
    if action == "remove":
        expected.append("remove:False:1")
    if action == "keep":
        expected.append("persist-keep")
    expected.append(f"outcome:{outcome}")
    if action != "quit":
        expected.append("progress:1/1")
    assert fixture.events == [*expected, "finish"]
    assert fixture.final == counts


def test_previous_keep_avoids_follow_and_catalog_reads() -> None:
    """A persisted keep bypasses every external album and artist observation."""
    fixture = MemoryReview(previous=True)
    review_albums(fixture, fixture)
    assert fixture.events == [
        "load",
        "previous",
        "outcome:previously kept",
        "progress:1/1",
        "finish",
    ]
    assert fixture.final == ReviewCounts(kept=1)


def test_empty_review_only_presents_zero_counts() -> None:
    """Empty inputs retain the completion summary without progress or reads."""
    fixture = MemoryReview(empty=True)
    review_albums(fixture, fixture)
    assert fixture.events == ["load", "finish"]
    assert fixture.final == ReviewCounts()


def test_assessed_keep_avoids_live_membership_and_prompts() -> None:
    """A sufficient liked proportion completes after the original artist check."""
    fixture = MemoryReview(assessment=_evaluation("keep"))
    review_albums(fixture, fixture)
    assert fixture.events == [
        "load",
        "previous",
        "follow",
        "evaluate",
        "outcome:keep",
        "progress:1/1",
        "finish",
    ]
    assert fixture.final == ReviewCounts(kept=1, followed=1)


def test_zero_live_likes_removes_without_choice_or_live_count_message() -> None:
    """Zero current membership preserves the original automatic removal path."""
    fixture = MemoryReview(liked=0)
    review_albums(fixture, fixture)
    assert fixture.events[4:] == [
        "candidate",
        "live",
        "remove:True:0",
        "outcome:auto-removed",
        "progress:1/1",
        "finish",
    ]
    assert fixture.final == ReviewCounts(removed=1, followed=1)


def test_unknown_track_identifiers_require_confirmation() -> None:
    """Missing identifiers bypass membership reads and retain the manual prompt."""
    fixture = MemoryReview(assessment=_evaluation(known_track=False))
    review_albums(fixture, fixture)
    assert "live" not in fixture.events
    assert fixture.events[4:8] == [
        "candidate",
        "display-live:None",
        "choose",
        "remove:False:None",
    ]


@pytest.mark.parametrize(
    "failure",
    ["follow", "evaluate", "live", "choose", "remove:False:1", "progress:1/1"],
)
def test_review_failure_does_not_emit_success_after_boundary(failure: str) -> None:
    """Failures stop at the observed boundary without a completion summary.

    Args:
        failure: Read, write, interaction, or cancellation boundary to interrupt.
    """
    fixture = MemoryReview(fail=failure)
    with pytest.raises(RuntimeError, match=failure):
        review_albums(fixture, fixture)
    assert fixture.events[-1] == failure
    assert fixture.final is None
