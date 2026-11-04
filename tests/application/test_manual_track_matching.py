"""Explicit historical choices bypass qualification but retain playlist decisions."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.historical_resolution import HistoricalResolution
from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.manual_track_matching import ManualTrackMatching
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from tests.application.test_historical_resolution import ResolutionMemory
from tests.application.test_historical_resolution import _match
from tests.application.test_historical_resolution import _selection
from tests.support.runtime_resources import MessageList


@dataclass
class ManualScript:
    """Own search results, explicit answers and cancellation checkpoints.

    Args:
        candidates: Search results offered in their original order.
        answer: Explicit operator decision.
        cancel_at: Cancellation checkpoint, or zero to continue.
        checks: Number of observed checkpoints.
        events: Ordered search and interaction observations.
    """

    candidates: tuple[SpotifyTrackMatch, ...] = ()
    answer: str = ""
    cancel_at: int = 0
    checks: int = 0
    events: list[str] = field(default_factory=list)

    def check(self) -> None:
        """Stop at the scripted cancellation checkpoint.

        Raises:
            BlastFromPastCancelledError: The scripted checkpoint is reached.
        """
        self.checks += 1
        if self.checks == self.cancel_at:
            raise BlastFromPastCancelledError

    async def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Record a broad search and return the scripted results.

        Args:
            scrobble: Original historical play.

        Returns:
            Scripted track candidates.
        """
        self.events.append(f"search:{scrobble.track}")
        return self.candidates

    async def choose(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> str:
        """Record the offered play and return the scripted decision.

        Args:
            scrobble: Original historical play.
            candidates: Offered track observations in search order.

        Returns:
            Scripted candidate identity or rejection.
        """
        assert candidates == self.candidates
        self.events.append(f"choose:{scrobble.track}")
        return self.answer


@pytest.mark.parametrize("answer", ["", "other"])
async def test_manual_choice_accepts_low_similarity_or_explicit_no_match(
    answer: str,
) -> None:
    """Accept an explicit low-similarity choice without applying automatic gates.

    Args:
        answer: Scripted explicit decision.
    """
    candidate = _match("other", score=0.01)
    script = ManualScript((candidate,), answer)
    result = await ManualTrackMatching(script, script, script).run(
        _selection("song").scrobble
    )
    assert result == (candidate if answer else None)
    assert script.events == ["search:song", "choose:song"]


async def test_empty_search_still_requires_explicit_rejection() -> None:
    """Present empty results rather than silently dropping the historical play."""
    script = ManualScript()
    assert (
        await ManualTrackMatching(script, script, script).run(
            _selection("empty").scrobble
        )
        is None
    )
    assert script.events == ["search:empty", "choose:empty"]


async def test_unoffered_identity_is_rejected() -> None:
    """Reject an identity that was never offered to the operator."""
    script = ManualScript((_match(),), "unoffered")
    with pytest.raises(SpotifyTrackResolutionError, match="not offered"):
        await ManualTrackMatching(script, script, script).run(
            _selection("song").scrobble
        )


@pytest.mark.parametrize("boundary", [1, 2, 3])
async def test_cancellation_precedes_search_choice_and_acceptance(
    boundary: int,
) -> None:
    """Stop at each cancellation boundary without accepting a partial decision.

    Args:
        boundary: Cancellation checkpoint to interrupt.
    """
    script = ManualScript((_match(),), "same", boundary)
    with pytest.raises(BlastFromPastCancelledError):
        await ManualTrackMatching(script, script, script).run(
            _selection("song").scrobble
        )
    assert script.events == ["search:song", "choose:song"][: boundary - 1]


@pytest.mark.parametrize("present", [False, True])
async def test_manual_choices_retain_order_membership_duplicates_and_live_liked_status(
    present: bool,
) -> None:
    """Apply the existing duplicate and membership policy to explicit choices.

    Args:
        present: Whether the chosen track already exists in the playlist.
    """
    auto = ResolutionMemory(liked_ids={"chosen"})
    manual = ManualScript((_match("chosen", score=0.01),), "chosen")
    workflow = HistoricalResolution(
        auto, manual, MessageList([]), ManualTrackMatching(manual, manual, manual)
    )
    playlist = PlaylistState(1, frozenset({"chosen"}) if present else frozenset())
    result = await workflow.run((_selection("first"), _selection("second")), playlist)
    assert [item.action for item in result.results] == (
        ["already present", "already present"]
        if present
        else ["added", "duplicate selection"]
    )
    assert all(item.match and item.match.liked for item in result.results)
    assert all(item.qualifying_matches == 0 for item in result.results)
    assert [item.spotify_id for item in result.pending_matches] == (
        [] if present else ["chosen"]
    )


async def test_automatic_ambiguity_keeps_existing_ranking_without_manual_search() -> (
    None
):
    """Preserve automatic ranking when several candidates qualify."""
    auto = ResolutionMemory(matches={"song": (_match("first"), _match("second"))})
    manual = ManualScript(answer="unexpected")
    workflow = HistoricalResolution(
        auto, manual, MessageList([]), ManualTrackMatching(manual, manual, manual)
    )
    result = await workflow.run((_selection("song"),), PlaylistState(0, frozenset()))
    assert result.results[0].match == _match("first")
    assert result.results[0].qualifying_matches == 2
    assert manual.events == []


async def test_manual_rejection_preserves_other_automatic_results() -> None:
    """Continue resolving the batch after an explicit no-match decision."""
    auto = ResolutionMemory(matches={"good": (_match(),)})
    manual = ManualScript()
    workflow = HistoricalResolution(
        auto, manual, MessageList([]), ManualTrackMatching(manual, manual, manual)
    )
    result = await workflow.run(
        (_selection("missing"), _selection("good")), PlaylistState(0, frozenset())
    )
    assert [item.action for item in result.results] == ["no match", "added"]
    assert result.pending_matches == (_match(),)
