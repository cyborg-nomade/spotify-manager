"""Standard-library values shared by nightly automation and its adapters."""

from dataclasses import dataclass
from datetime import timedelta


ACTIVE_STATUSES = {"queued", "running", "waiting", "cancelling"}
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
POLL_SECONDS = 20
BLOCKED_RETRY_SECONDS = 60
REQUEST_RETRY_SECONDS = 20
MANUAL_MAX_RUNTIME = timedelta(hours=5)
DURABLE_ARTIFACT_FILENAMES = frozenset(
    {
        "albums_total_new.json",
        "liked_tracks_total.json",
        "artists_total.json",
        "lastfmstats-man-et-arms.json",
    }
)


class AutomationError(RuntimeError):
    """Raised when the nightly refresh cannot finish safely."""


class DeadlineReachedError(AutomationError):
    """Raised when the nightly maintenance window closes."""


class JobLostError(AutomationError):
    """Raised when a Space restart discards an in-memory job handle."""


class ApiError(AutomationError):
    """Represent one non-transient response from the Space API."""

    def __init__(self, status: int, payload: object) -> None:
        """Retain the HTTP status and decoded FastAPI response.

        Args:
            status: Original rejected HTTP status.
            payload: Original unvalidated decoded API response.
        """
        super().__init__(f"Space API returned HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


@dataclass(frozen=True)
class JobSpec:
    """One scheduled API job and its polling routes.

    Args:
        label: Original visible job label.
        command: Original API command identity.
        start_path: Original start path including query parameters.
        status_path: Original status route with its job identity placeholder.
        cancel_path: Original cancellation route with its job identity placeholder.
    """

    label: str
    command: str
    start_path: str
    status_path: str
    cancel_path: str


def refresh_jobs(
    *, full_rebuild: bool, scrobble_rebuild: bool = False
) -> tuple[JobSpec, ...]:
    """Build the original history-first four-job request manifest.

    Args:
        full_rebuild: Original independent Spotify mirror rebuild mode.
        scrobble_rebuild: Original independent history rebuild mode.

    Returns:
        Original ordered commands, query parameters and status/cancel routes.
    """
    rebuild = str(full_rebuild).lower()
    start = "/commands/update-scrobble-history?dry_run=false"
    if scrobble_rebuild:
        start += "&full_rebuild=true"
    jobs = [
        JobSpec(
            "Last.fm scrobble history",
            "update_scrobble_history",
            start,
            "/commands/update-scrobble-history-jobs/{job_id}",
            "/commands/update-scrobble-history-jobs/{job_id}/cancel",
        )
    ]
    for resource in ("albums", "tracks", "artists"):
        jobs.append(
            JobSpec(
                f"Spotify {resource} mirror",
                f"refresh_library_mirror_{resource}",
                f"/commands/refresh-library-mirrors/{resource}?full_rebuild={rebuild}",
                "/commands/library-analysis-jobs/{job_id}",
                "/commands/library-analysis-jobs/{job_id}/cancel",
            )
        )
    return tuple(jobs)


JOBS = refresh_jobs(full_rebuild=False)
FULL_REBUILD_JOBS = refresh_jobs(full_rebuild=True)
