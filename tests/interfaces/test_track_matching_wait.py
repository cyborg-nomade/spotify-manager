"""Do not publish or consume a manual choice after invocation cancellation."""

import pytest

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.domain.history import Scrobble
from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.track_matching import WebTrackMatching


async def test_cancel_before_prompt_never_publishes_waiting_state() -> None:
    """Give cancellation precedence over a newly requested operator prompt."""
    job = PlaylistJob(BlastJobResult(job_id="cancelled", status="cancelling"))
    job.cancel_event.set()
    interaction = WebTrackMatching(jobs._playlist_context(), job)
    with pytest.raises(BlastFromPastCancelledError):
        await interaction.choose(Scrobble("Song", "Artist", "Album", 1), ())
    assert job.result.status == "cancelling"
    assert job.result.track_match_pending_choice is None


def test_cancel_after_submission_never_consumes_the_selected_track() -> None:
    """Discard acceptance when cancellation wins before worker consumption."""
    job = PlaylistJob(BlastJobResult(job_id="cancelled", status="cancelling"))
    job.submitted_choice = "selected"
    job.cancel_event.set()
    with pytest.raises(BlastFromPastCancelledError):
        WebTrackMatching(jobs._playlist_context(), job).consume()
    assert job.result.status == "cancelling"
