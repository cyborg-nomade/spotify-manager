"""Protect the original atomic submission and cancellation outcomes."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier

import pytest
from fastapi import HTTPException

from spotify_manager import api
from spotify_manager.interfaces.http import jobs as http_jobs
from spotify_manager.interfaces.http.models.requeue import RequeuePendingChoice
from spotify_manager.interfaces.http.models.track_matching import (
    TrackMatchPendingChoice,
)


@dataclass(frozen=True)
class Interaction:
    """Describe an original choice or ordering channel through public facades.

    Args:
        command: Owning command identity.
        pending_field: Original pending interaction response field.
        create: Waiting view factory without any external client.
        submit: Complete original submission invocation.
        cancel: Original cancellation endpoint.
        choice: Accepted token retained until worker consumption.
        order: Accepted order, including an empty tuple where originally valid.
    """

    command: str
    pending_field: str
    create: Callable[[], api.BlastJobResult]
    submit: Callable[[str], api.BlastJobResult]
    cancel: Callable[[str], api.BlastJobResult]
    choice: str
    order: tuple[str, ...] | None


def _queue_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="fill_queue_from_lastfm",
        status="waiting",
        queue_pending_choice=api.QueuePendingChoice(
            artist="Artist", base_rank=1, score=1.0
        ),
    )


def _order_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="flush_slow_listening",
        status="waiting",
        slow_listening_pending_choice=api.SlowListeningPendingChoice(
            kind="release_order", artist="Artist"
        ),
    )


def _slow_album_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="flush_slow_listening",
        status="waiting",
        slow_listening_pending_choice=api.SlowListeningPendingChoice(
            kind="release", artist="Artist", request_id="album-request"
        ),
    )


def _submit_slow_album(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_slow_listening_track(
        job_id,
        api.SlowListeningChoiceRequest(choice="skip_album", request_id="album-request"),
    )


def _requeue_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="flush_requeue_for_a_dream",
        status="waiting",
        requeue_pending_choice=RequeuePendingChoice(
            request_id="album-request",
            artist="Artist",
            source_track="Current",
            source_release="First",
            release_id="second",
            release_name="Second",
            release_type="Album",
            release_date="2021",
            total_tracks=2,
        ),
    )


def _submit_requeue(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_requeue_album(
        job_id, api.RequeueChoiceRequest(choice="accept", request_id="album-request")
    )


def _checklist_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="plan_discographies",
        status="waiting",
        discography_pending_choice=api.DiscographyPendingChoice(kind="releases"),
    )


def _submit_queue(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_queue_artist(job_id, api.QueueChoiceRequest(choice="skip"))


def _submit_order(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_slow_listening_track(
        job_id, api.SlowListeningChoiceRequest(choice="order", order=[])
    )


def _submit_checklist(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_discography(
        job_id, api.DiscographyChoiceRequest(choice="none", release_ids=[])
    )


def _blast_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="blast_from_the_past",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Song - Album", candidates=[]
        ),
    )


def _daily_match_view() -> api.BlastJobResult:
    return _blast_match_view().model_copy(update={"command": "daily_mind_radio"})


def _submit_blast_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_blast_track(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _submit_daily_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_daily_mind_radio_track(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _found_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="found_art",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Title", candidates=[], kind="track"
        ),
    )


def _submit_found_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_found_art(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _annual_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="new_year",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Title", candidates=[], kind="album"
        ),
    )


def _submit_annual_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_new_year_match(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _sauvignon_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="fill_sauvignon_from_lastfm",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Title", candidates=[], kind="album"
        ),
    )


def _submit_sauvignon_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_sauvignon_match(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _old_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="something_old",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Title", candidates=[], kind="track"
        ),
    )


def _submit_old_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_something_old_match(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


def _palace_match_view() -> api.BlastJobResult:
    return api.BlastJobResult(
        job_id="owner",
        command="fill_palace_of_memory",
        status="waiting",
        track_match_pending_choice=TrackMatchPendingChoice(
            request_id="current", scrobble="Artist - Title", candidates=[], kind="album"
        ),
    )


def _submit_palace_match(job_id: str) -> api.BlastJobResult:
    return api.cmd_choose_palace_match(
        job_id, api.TrackMatchChoiceRequest(request_id="current", choice="")
    )


INTERACTIONS = (
    Interaction(
        "flush_requeue_for_a_dream",
        "requeue_pending_choice",
        _requeue_view,
        _submit_requeue,
        api.cmd_cancel_requeue_for_a_dream_job,
        "accept",
        None,
    ),
    Interaction(
        "found_art",
        "track_match_pending_choice",
        _found_match_view,
        _submit_found_match,
        api.cmd_cancel_found_art_job,
        "",
        None,
    ),
    Interaction(
        "new_year",
        "track_match_pending_choice",
        _annual_match_view,
        _submit_annual_match,
        api.cmd_cancel_new_year_job,
        "",
        None,
    ),
    Interaction(
        "fill_sauvignon_from_lastfm",
        "track_match_pending_choice",
        _sauvignon_match_view,
        _submit_sauvignon_match,
        api.cmd_cancel_sauvignon_job,
        "",
        None,
    ),
    Interaction(
        "something_old",
        "track_match_pending_choice",
        _old_match_view,
        _submit_old_match,
        api.cmd_cancel_something_old_job,
        "",
        None,
    ),
    Interaction(
        "fill_palace_of_memory",
        "track_match_pending_choice",
        _palace_match_view,
        _submit_palace_match,
        api.cmd_cancel_palace_of_memory_job,
        "",
        None,
    ),
    Interaction(
        "blast_from_the_past",
        "track_match_pending_choice",
        _blast_match_view,
        _submit_blast_match,
        api.cmd_cancel_blast_job,
        "",
        None,
    ),
    Interaction(
        "daily_mind_radio",
        "track_match_pending_choice",
        _daily_match_view,
        _submit_daily_match,
        api.cmd_cancel_daily_mind_radio_job,
        "",
        None,
    ),
    Interaction(
        "fill_queue_from_lastfm",
        "queue_pending_choice",
        _queue_view,
        _submit_queue,
        api.cmd_cancel_queue_fill_job,
        "skip",
        None,
    ),
    Interaction(
        "flush_slow_listening",
        "slow_listening_pending_choice",
        _order_view,
        _submit_order,
        api.cmd_cancel_slow_listening_job,
        "order",
        (),
    ),
    Interaction(
        "flush_slow_listening",
        "slow_listening_pending_choice",
        _slow_album_view,
        _submit_slow_album,
        api.cmd_cancel_slow_listening_job,
        "skip_album",
        None,
    ),
    Interaction(
        "plan_discographies",
        "discography_pending_choice",
        _checklist_view,
        _submit_checklist,
        api.cmd_cancel_discography_job,
        "none",
        (),
    ),
)


def _interaction_name(interaction: Interaction) -> str:
    return interaction.command


def _invoke(
    action: Callable[[str], api.BlastJobResult], barrier: Barrier, job_id: str
) -> int:
    barrier.wait(timeout=5)
    try:
        action(job_id)
    except HTTPException as exc:
        return exc.status_code
    return 200


def _assert_cancelled(job: api._BlastJob, interaction: Interaction) -> None:
    assert job.result.status == "cancelling"
    assert getattr(job.result, interaction.pending_field) is None
    assert job.cancel_event.is_set()
    assert job.choice_event.is_set()
    assert len(job.result.logs) == 1
    assert job.result.logs[0].message == job.result.detail


@pytest.mark.parametrize("interaction", INTERACTIONS, ids=_interaction_name)
@pytest.mark.parametrize("iteration", range(8))
def test_choice_cancel_race_has_only_original_atomic_outcomes(
    interaction: Interaction, iteration: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race real endpoint calls without starting a worker or writing effects.

    Args:
        interaction: Original independent submission channel.
        iteration: Repeated scheduling opportunity.
        monkeypatch: Isolate the original process-local registry.
    """
    owner = api._BlastJob(result=interaction.create())
    other = api._BlastJob(result=api.BlastJobResult(job_id=f"other-{iteration}"))
    monkeypatch.setattr(http_jobs, "_blast_jobs", {"owner": owner, "other": other})
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        submit = pool.submit(_invoke, interaction.submit, barrier, "owner")
        cancel = pool.submit(_invoke, interaction.cancel, barrier, "owner")
        submitted, cancelled = submit.result(timeout=10), cancel.result(timeout=10)
    assert cancelled == 200
    assert submitted in {200, 409}
    _assert_cancelled(owner, interaction)
    assert owner.submitted_choice == (interaction.choice if submitted == 200 else None)
    assert owner.submitted_order == (interaction.order if submitted == 200 else None)
    assert not other.cancel_event.is_set() and not other.choice_event.is_set()
    assert not other.result.logs


@pytest.mark.parametrize("interaction", INTERACTIONS, ids=_interaction_name)
def test_accepted_then_cancelled_choice_preserves_detached_submission_view(
    interaction: Interaction, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep accepted ordering and stale snapshots unchanged after cancellation.

    Args:
        interaction: Original submission channel.
        monkeypatch: Isolate the original process-local registry.
    """
    job = api._BlastJob(result=interaction.create())
    monkeypatch.setattr(http_jobs, "_blast_jobs", {"owner": job})
    submitted = interaction.submit("owner")
    interaction.cancel("owner")
    assert submitted.status == "running" and not submitted.logs
    assert job.submitted_choice == interaction.choice
    assert job.submitted_order == interaction.order
    _assert_cancelled(job, interaction)
    with pytest.raises(HTTPException) as error:
        interaction.submit("owner")
    assert error.value.status_code == 409
