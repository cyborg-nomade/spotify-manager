"""Process-local handles owned by the threaded HTTP delivery adapter."""

from dataclasses import dataclass
from dataclasses import field
from threading import Event

from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.interfaces.http.models.jobs import BlastJobResult


@dataclass
class AnalysisJob:
    """Keep the analysis view and cancellation signal under its registry lock.

    Args:
        result: Original pollable analysis view.
        cancel_event: Worker-owned cancellation signal.
        next_log_sequence: Next accepted event's original sequence number.
    """

    result: AnalysisJobResult
    cancel_event: Event
    next_log_sequence: int = 1


@dataclass
class PlaylistJob:
    """Keep playlist/history interaction signals separate for each job.

    Args:
        result: Original wide pollable view, presented by feature adapters.
        next_log_sequence: Next accepted event's original sequence number.
        choice_event: Submission wake-up signal, separate from cancellation.
        cancel_event: Cancellation request observed at existing safe boundaries.
        submitted_choice: Accepted choice token awaiting worker consumption.
        submitted_order: Accepted ordered release IDs awaiting consumption.
    """

    result: BlastJobResult
    next_log_sequence: int = 1
    choice_event: Event = field(default_factory=Event)
    cancel_event: Event = field(default_factory=Event)
    submitted_choice: str | None = None
    submitted_order: tuple[str, ...] | None = None
