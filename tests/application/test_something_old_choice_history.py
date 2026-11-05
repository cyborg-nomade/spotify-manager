"""Verify completed-choice evidence, isolation and accepted-effect recovery."""

from dataclasses import dataclass
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from spotify_manager.application.history_refresh import HistoryRefresh
from spotify_manager.application.something_old_history import SomethingOldChoiceHistory
from spotify_manager.application.something_old_run import SomethingOld
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import choice_identity
from tests.application.test_something_old_workflow import ScriptedHistory
from tests.support.queue_neighbors import NOW
from tests.support.something_old_choices import AppendOutcome
from tests.support.something_old_choices import ChoiceEffects
from tests.support.something_old_choices import ChoiceReader
from tests.support.something_old_choices import MemoryChoiceAccess
from tests.support.something_old_run import ARTIST
from tests.support.something_old_run import TRACK
from tests.support.something_old_run import OldObservations


def _workflow(effects: ChoiceEffects, reader: ChoiceReader) -> SomethingOld:
    return SomethingOld(
        effects,
        cast(HistoryRefresh, ScriptedHistory(effects)),
        "listener",
        choices=SomethingOldChoiceHistory(effects.storage),
        history_reader=reader,
    )


def _choice() -> ArtistChoice:
    return ArtistChoice(
        ARTIST.spotify_id,
        ARTIST.name,
        "Historical label",
        "spotify_top_tracks",
        NOW - timedelta(days=1),
        "destination",
        (TRACK.spotify_id,),
    )


@pytest.mark.parametrize("mode", ["lastfm_top_tracks", "spotify_top_tracks", "album"])
@pytest.mark.parametrize("preview", [False, True])
async def test_only_successfully_applied_modes_enter_shared_history(
    mode: str, preview: bool
) -> None:
    """Every mode records one accepted complete append; previews record none.

    Args:
        mode: Explicit operator source selection.
        preview: Suppress playlist, journal and completed-history writes.
    """
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(OldObservations(mode), access)
    reader = ChoiceReader(mode)
    result = await _workflow(effects, reader).run("destination", preview)
    assert result.action == ("would add" if preview else "added")
    assert [entry.count for entry in reader.shown[0]] == [0, 0, 0]
    assert len(access.stored.choices) == int(not preview)
    assert access.stored.pending == {}
    assert access.events == ([] if preview else ["save", "append", "save"])
    if not preview:
        choice = next(iter(access.stored.choices.values()))
        assert choice.artist_id == ARTIST.spotify_id and choice.mode == mode
        assert choice.provenance == "applied"


@pytest.mark.parametrize(
    "scenario,mode",
    [("quit-artist", "album"), ("quit-mode", "quit"), ("quit-album", "album")],
)
async def test_abandoned_choices_do_not_count(scenario: str, mode: str) -> None:
    """Artist, mode and album cancellation cannot become completed evidence.

    Args:
        scenario: Original cancellation boundary.
        mode: Explicit reader response.
    """
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(OldObservations(scenario), access)
    result = await _workflow(effects, ChoiceReader(mode)).run("destination", False)
    assert result.action == "cancelled"
    assert access.stored.choices == {} and access.stored.pending == {}
    assert access.saves == 0 and access.tracks == ()


async def test_changed_playlist_cannot_prepare_or_record_a_choice() -> None:
    """The original final empty check still precedes the intent and all writes."""
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(OldObservations("changed"), access)
    with pytest.raises(SomethingOldError, match="changed while"):
        await _workflow(effects, ChoiceReader()).run("destination", False)
    assert access.events == [] and access.stored.choices == {}


@pytest.mark.parametrize("accepted", [False, True])
async def test_intent_checkpoint_failure_prevents_append(accepted: bool) -> None:
    """Losing an intent response cannot authorize a Spotify write or count a choice.

    Args:
        accepted: Whether the prepared intent reached durable storage.
    """
    access = MemoryChoiceAccess(fail_save=1, accepted=accepted)
    effects = ChoiceEffects(OldObservations("spotify_top_tracks"), access)
    with pytest.raises(RuntimeError, match="history save interrupted"):
        await _workflow(effects, ChoiceReader()).run("destination", False)
    assert "append" not in access.events and access.tracks == ()
    assert access.stored.choices == {}
    resumed = _workflow(effects, ChoiceReader("quit"))
    await resumed.run("destination", False)
    assert access.stored.pending == {} and access.stored.choices == {}


@pytest.mark.parametrize("accepted", [False, True])
async def test_completed_checkpoint_failure_recovers_once_without_reappending(
    accepted: bool,
) -> None:
    """Restart records the full accepted selection or retains the accepted checkpoint.

    Args:
        accepted: Whether the completed-history checkpoint actually reached storage.
    """
    access = MemoryChoiceAccess(fail_save=2, accepted=accepted)
    effects = ChoiceEffects(OldObservations("spotify_top_tracks"), access)
    with pytest.raises(RuntimeError, match="history save interrupted"):
        await _workflow(effects, ChoiceReader()).run("destination", False)
    result = await _workflow(effects, ChoiceReader()).run("destination", False)
    assert result.action == "playlist not empty"
    assert len(access.stored.choices) == 1 and access.stored.pending == {}
    assert access.events.count("append") == 1
    choice = next(iter(access.stored.choices.values()))
    assert choice.provenance == ("applied" if accepted else "recovered")
    await _workflow(effects, ChoiceReader()).run("destination", False)
    assert len(access.stored.choices) == 1


@pytest.mark.parametrize("outcome", ["before", "partial", "after"])
async def test_recovery_requires_the_full_multiset_of_accepted_tracks(
    outcome: AppendOutcome,
) -> None:
    """Partial duplicate-track appends remain pending and never count as completed.

    Args:
        outcome: Lost response before, during or after a complete duplicate append.
    """
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(
        OldObservations("spotify_top_tracks"), access, selection=(TRACK, TRACK)
    )
    effects = replace(effects, outcome=outcome)
    with pytest.raises(RuntimeError, match="append interrupted"):
        await _workflow(effects, ChoiceReader()).run("destination", False)
    reader = ChoiceReader("quit")
    await _workflow(effects, reader).run("destination", False)
    assert len(access.stored.choices) == int(outcome == "after")
    assert bool(access.stored.pending) is (outcome == "partial")
    assert access.events.count("append") == 1


async def test_audit_failure_does_not_lose_accepted_choice_history() -> None:
    """Durable choice evidence precedes the separate legacy audit response."""
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(OldObservations("spotify_top_tracks", "audit"), access)
    with pytest.raises(RuntimeError, match="audit"):
        await _workflow(effects, ChoiceReader()).run("destination", False)
    assert len(access.stored.choices) == 1 and access.stored.pending == {}
    await _workflow(effects, ChoiceReader()).run("destination", False)
    assert len(access.stored.choices) == 1 and access.events.count("append") == 1


@pytest.mark.parametrize("preview", [False, True])
async def test_imported_audits_are_deduplicated_and_shown_without_selecting_a_mode(
    preview: bool,
) -> None:
    """Imports retain provenance; a current preview/quit never creates another choice.

    Args:
        preview: Keep the imported evidence detached from shared storage.
    """
    choice = replace(_choice(), provenance="audit")
    access = MemoryChoiceAccess(audits=(choice, choice))
    effects = ChoiceEffects(OldObservations("quit-mode"), access)
    reader = ChoiceReader("quit")
    await _workflow(effects, reader).run("destination", preview)
    assert reader.shown[0][1].count == 1
    assert reader.shown[0][1].provenance == "audit"
    assert len(access.stored.choices) == int(not preview)
    assert access.events == ([] if preview else ["save"])


async def test_imported_and_applied_event_share_one_identity() -> None:
    """Importing a matching audit cannot double count or replace stronger provenance."""
    choice = _choice()
    access = MemoryChoiceAccess(audits=(replace(choice, provenance="audit"),))
    access.stored.choices[choice_identity(choice)] = choice
    effects = ChoiceEffects(OldObservations("quit-mode"), access)
    reader = ChoiceReader("quit")
    await _workflow(effects, reader).run("destination", False)
    assert reader.shown[0][1].count == 1 and reader.shown[0][1].provenance == "applied"
    assert access.saves == 0


async def test_audit_reconciles_pending_intent_without_playlist_guessing() -> None:
    """A completed audit can reconcile an intent after its tracks were consumed."""
    choice = _choice()
    access = MemoryChoiceAccess(audits=(replace(choice, provenance="audit"),))
    access.stored.pending["destination"] = choice
    effects = ChoiceEffects(OldObservations("quit-mode"), access)
    await _workflow(effects, ChoiceReader("quit")).run("destination", False)
    assert len(access.stored.choices) == 1 and access.stored.pending == {}
    assert access.events == ["save"]


async def test_preview_reconciles_prior_effects_without_writing_shared_history() -> (
    None
):
    """A preview can inspect durable evidence but cannot change its checkpoint."""
    choice = _choice()
    access = MemoryChoiceAccess(tracks=choice.track_ids)
    access.stored.pending["destination"] = choice
    history = SomethingOldChoiceHistory(access)
    await history.load("destination", True)
    assert len(history.ledger.choices) == 1
    assert access.stored.choices == {} and access.stored.pending
    assert access.saves == 0


@dataclass
class InterruptedHistory:
    """Observe an operator interruption at a specific new checkpoint boundary.

    Args:
        fail_at: Check occurrence that cancels the invocation.
        calls: Observed cancellation boundaries.
    """

    fail_at: int
    calls: int = 0

    def check(self) -> None:
        """Raise cancellation at the configured boundary.

        Raises:
            RuntimeError: The current operator action cancels execution.
        """
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("operator cancelled")


@pytest.mark.parametrize("boundary", [1, 2])
async def test_new_checkpoint_keeps_cancellation_before_append(boundary: int) -> None:
    """Cancellation before or after preparing the intent cannot append or count it.

    Args:
        boundary: Check before persistence or immediately after its acceptance.
    """
    access = MemoryChoiceAccess()
    effects = ChoiceEffects(OldObservations("spotify_top_tracks"), access)
    workflow = replace(
        _workflow(effects, ChoiceReader()),
        choices=SomethingOldChoiceHistory(access, InterruptedHistory(boundary)),
    )
    with pytest.raises(RuntimeError, match="operator cancelled"):
        await workflow.run("destination", False)
    assert "append" not in access.events and access.stored.choices == {}
    assert bool(access.stored.pending) is (boundary == 2)
