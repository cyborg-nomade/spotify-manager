"""Run the four durable library refreshes through the deployed web API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import time as datetime_time
from datetime import timedelta
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request
from urllib.request import urlopen
from zoneinfo import ZoneInfo


DEFAULT_SPACE_URL = "https://cyborg-nomade-spotify-manager.hf.space"
BERLIN = ZoneInfo("Europe/Berlin")
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
        """Retain the HTTP status and decoded FastAPI response."""
        super().__init__(f"Space API returned HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


@dataclass(frozen=True)
class JobSpec:
    """One scheduled API job and its polling routes."""

    label: str
    command: str
    start_path: str
    status_path: str
    cancel_path: str


def refresh_jobs(*, full_rebuild: bool) -> tuple[JobSpec, ...]:
    """Build the four API jobs for an incremental or full refresh night."""
    rebuild = str(full_rebuild).lower()
    return (
        JobSpec(
            label="Last.fm scrobble history",
            command="update_scrobble_history",
            start_path="/commands/update-scrobble-history?dry_run=false",
            status_path="/commands/update-scrobble-history-jobs/{job_id}",
            cancel_path="/commands/update-scrobble-history-jobs/{job_id}/cancel",
        ),
        *(
            JobSpec(
                label=f"Spotify {resource} mirror",
                command=f"refresh_library_mirror_{resource}",
                start_path=(
                    f"/commands/refresh-library-mirrors/{resource}"
                    f"?full_rebuild={rebuild}"
                ),
                status_path="/commands/library-analysis-jobs/{job_id}",
                cancel_path="/commands/library-analysis-jobs/{job_id}/cancel",
            )
            for resource in ("albums", "tracks", "artists")
        ),
    )


JOBS = refresh_jobs(full_rebuild=False)
FULL_REBUILD_JOBS = refresh_jobs(full_rebuild=True)


def maintenance_deadline(now: datetime) -> datetime:
    """Return 05:00 Berlin for a scheduled run, or five hours for a manual run."""
    local_now = now.astimezone(BERLIN)
    if local_now.hour < 5:
        deadline_date = local_now.date()
    elif local_now.hour >= 22:
        deadline_date = (local_now + timedelta(days=1)).date()
    else:
        return now + MANUAL_MAX_RUNTIME
    local_deadline = datetime.combine(
        deadline_date,
        datetime_time(hour=5),
        tzinfo=BERLIN,
    )
    return local_deadline.astimezone(UTC)


def scheduled_window_is_open(now: datetime) -> bool:
    """Return whether a delayed scheduled run is still inside 22:00-05:00."""
    local_hour = now.astimezone(BERLIN).hour
    return local_hour >= 22 or local_hour < 5


def maintenance_window_start(now: datetime) -> datetime:
    """Return the opening 22:00 boundary for the active Berlin window."""
    local_now = now.astimezone(BERLIN)
    window_date = (
        local_now.date() - timedelta(days=1)
        if local_now.hour < 5
        else local_now.date()
    )
    local_start = datetime.combine(
        window_date,
        datetime_time(hour=22),
        tzinfo=BERLIN,
    )
    return local_start.astimezone(UTC)


def required_environment() -> tuple[str, str, str]:
    """Return validated connection settings without ever printing secrets."""
    space_url = os.environ.get("SPACE_URL", DEFAULT_SPACE_URL).rstrip("/") + "/"
    hf_token = os.environ.get("HF_SPACE_TOKEN", "").strip()
    automation_token = os.environ.get("AUTOMATION_TOKEN", "").strip()
    missing = [
        name
        for name, value in (
            ("HF_SPACE_TOKEN", hf_token),
            ("AUTOMATION_TOKEN", automation_token),
        )
        if not value
    ]
    if missing:
        raise AutomationError("Missing workflow secrets: " + ", ".join(missing))
    return space_url, hf_token, automation_token


def _decode_response(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AutomationError("Space returned a non-JSON response.") from exc


class SpaceClient:
    """Small authenticated HTTP client with bounded transient retries."""

    def __init__(
        self,
        space_url: str,
        hf_token: str,
        automation_token: str,
        deadline: datetime,
    ) -> None:
        """Configure the Space endpoint, credentials, and hard deadline."""
        self.space_url = space_url
        self.deadline = deadline
        self.headers = {
            "Authorization": f"Bearer {hf_token}",
            "X-Automation-Token": automation_token,
            "User-Agent": "spotify-manager-nightly-refresh/1",
        }

    def remaining_seconds(self) -> float:
        """Return seconds left in the maintenance window."""
        return (self.deadline - datetime.now(UTC)).total_seconds()

    def sleep(self, seconds: int) -> None:
        """Sleep without crossing the configured maintenance deadline."""
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise DeadlineReachedError("The 05:00 Berlin maintenance deadline arrived.")
        time.sleep(min(seconds, remaining))

    def request(
        self,
        method: str,
        path: str,
        *,
        retry_transient: bool = True,
        deadline: datetime | None = None,
    ) -> Any:
        """Issue one JSON request, retrying wake-up and gateway failures."""
        request_deadline = deadline or self.deadline
        while datetime.now(UTC) < request_deadline:
            request = Request(
                urljoin(self.space_url, path.lstrip("/")),
                method=method,
                headers=self.headers,
                data=b"" if method == "POST" else None,
            )
            try:
                with urlopen(request, timeout=60) as response:
                    return _decode_response(response.read())
            except HTTPError as exc:
                payload = _decode_response(exc.read())
                if retry_transient and exc.code in TRANSIENT_HTTP_STATUSES:
                    print(f"Space returned HTTP {exc.code}; retrying.", flush=True)
                    self.sleep(REQUEST_RETRY_SECONDS)
                    continue
                raise ApiError(exc.code, payload) from exc
            except (TimeoutError, URLError) as exc:
                if not retry_transient:
                    raise AutomationError(f"Could not reach the Space: {exc}") from exc
                print("Space connection interrupted; retrying.", flush=True)
                self.sleep(REQUEST_RETRY_SECONDS)
        raise DeadlineReachedError(
            "The maintenance deadline arrived during an API call."
        )


def conflict_detail(error: ApiError) -> dict[str, Any]:
    """Normalize FastAPI's nested HTTP 409 detail object."""
    if not isinstance(error.payload, dict):
        return {}
    detail = error.payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def start_job(client: SpaceClient, spec: JobSpec) -> str:
    """Start or reconnect to one job, waiting out unrelated playlist work."""
    while True:
        try:
            payload = client.request(
                "POST",
                spec.start_path,
                retry_transient=True,
            )
        except ApiError as exc:
            if exc.status != 409:
                raise
            detail = conflict_detail(exc)
            job_id = str(detail.get("job_id") or "")
            blocker = str(detail.get("command") or "")
            if job_id and (not blocker or blocker == spec.command):
                print(f"Reconnected to existing {spec.label} job {job_id}.", flush=True)
                return job_id
            print(
                f"{spec.label} is blocked by {blocker or 'another active job'}; "
                "waiting.",
                flush=True,
            )
            client.sleep(BLOCKED_RETRY_SECONDS)
            continue
        if not isinstance(payload, dict) or not payload.get("job_id"):
            raise AutomationError(f"{spec.label} returned no job id.")
        job_id = str(payload["job_id"])
        print(f"Started {spec.label} as {job_id}.", flush=True)
        return job_id


def cancel_job(client: SpaceClient, spec: JobSpec, job_id: str) -> None:
    """Ask the Space to stop one active job at its next durable boundary."""
    print(f"Cancelling {spec.label} at the maintenance deadline.", flush=True)
    grace_deadline = datetime.now(UTC) + timedelta(minutes=3)
    try:
        client.request(
            "POST",
            spec.cancel_path.format(job_id=job_id),
            retry_transient=False,
            deadline=grace_deadline,
        )
    except ApiError as exc:
        if exc.status not in {404, 409}:
            raise


def poll_job(client: SpaceClient, spec: JobSpec, job_id: str) -> str:
    """Poll one job until completion, pause, failure, restart, or deadline."""
    previous: tuple[str, str] | None = None
    while True:
        if client.remaining_seconds() <= 0:
            cancel_job(client, spec, job_id)
            return "deadline"
        try:
            payload = client.request(
                "GET",
                spec.status_path.format(job_id=job_id),
            )
        except ApiError as exc:
            if exc.status == 404:
                raise JobLostError(f"Lost {spec.label} after a Space restart.") from exc
            raise
        if not isinstance(payload, dict):
            raise AutomationError(f"{spec.label} returned an invalid job status.")
        status = str(payload.get("status") or "")
        detail = str(payload.get("detail") or "")
        current = (status, detail)
        if current != previous:
            print(f"{spec.label}: {status} - {detail}", flush=True)
            previous = current
        if status == "completed":
            return status
        if status == "paused":
            return status
        if status == "cancelled":
            return "paused"
        if status == "failed":
            raise AutomationError(f"{spec.label} ended as {status}: {detail}")
        if status not in ACTIVE_STATUSES:
            raise AutomationError(f"{spec.label} returned unknown status {status!r}.")
        client.sleep(POLL_SECONDS)


def run_job(client: SpaceClient, spec: JobSpec) -> str:
    """Run one resumable job, restarting its API handle after Space restarts."""
    while True:
        job_id = start_job(client, spec)
        try:
            return poll_job(client, spec, job_id)
        except JobLostError:
            print(
                f"{spec.label} handle was lost; resuming from its checkpoint.",
                flush=True,
            )


def run_nightly_refresh(
    client: SpaceClient,
    jobs: tuple[JobSpec, ...] = JOBS,
    *,
    freshness_threshold: datetime | None = None,
) -> int:
    """Run all refreshes serially within the maintenance window."""
    print(
        "Nightly refresh deadline: "
        f"{client.deadline.astimezone(BERLIN).isoformat()} (Europe/Berlin)",
        flush=True,
    )
    client.request("GET", "/health")
    print("Space is awake and healthy.", flush=True)
    if freshness_threshold is not None and durable_artifacts_are_fresh(
        client,
        freshness_threshold,
    ):
        print(
            "All four durable artifacts were already refreshed during this "
            "maintenance window; skipping the duplicate trigger.",
            flush=True,
        )
        return 0
    mode = "full rebuild" if jobs == FULL_REBUILD_JOBS else "incremental"
    print(f"Refresh mode: {mode}.", flush=True)
    for index, spec in enumerate(jobs):
        result = run_job(client, spec)
        if result == "paused":
            print(
                f"{spec.label} paused cleanly; remaining jobs will resume tomorrow.",
                flush=True,
            )
            return 0
        if result == "deadline":
            print("Maintenance window closed; progress was saved.", flush=True)
            return 0
        print(f"Completed {spec.label} ({index + 1}/{len(jobs)}).", flush=True)
    print("All nightly library refreshes completed.", flush=True)
    return 0


def durable_artifacts_are_fresh(
    client: SpaceClient,
    threshold: datetime,
) -> bool:
    """Return whether every durable artifact changed after the window opened."""
    payload = client.request("GET", "/library-mirrors/status")
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return False
    updated: dict[str, datetime] = {}
    for item in files:
        if not isinstance(item, dict) or not item.get("exists"):
            continue
        filename = str(item.get("filename") or "")
        raw_updated_at = item.get("updated_at")
        if filename not in DURABLE_ARTIFACT_FILENAMES or not isinstance(
            raw_updated_at,
            str,
        ):
            continue
        try:
            timestamp = datetime.fromisoformat(raw_updated_at)
        except ValueError:
            continue
        if timestamp.tzinfo is not None:
            updated[filename] = timestamp.astimezone(UTC)
    return DURABLE_ARTIFACT_FILENAMES <= updated.keys() and all(
        updated[filename] >= threshold for filename in DURABLE_ARTIFACT_FILENAMES
    )


def run_connection_check(client: SpaceClient) -> int:
    """Verify authentication and durable artifacts without starting jobs."""
    client.request("GET", "/health")
    auth = client.request("GET", "/auth/check")
    if not isinstance(auth, dict) or auth.get("status") != "ok":
        raise AutomationError("The Space automation token was not accepted.")
    status = client.request("GET", "/library-mirrors/status")
    files = status.get("files") if isinstance(status, dict) else None
    if not isinstance(files, list) or len(files) != len(JOBS):
        raise AutomationError("The durable library-data status is incomplete.")
    missing = [
        str(item.get("filename") or "unknown")
        for item in files
        if not isinstance(item, dict) or not item.get("exists")
    ]
    if missing:
        raise AutomationError("Durable artifacts are missing: " + ", ".join(missing))
    print("Automation authentication and all four durable artifacts are healthy.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Build the authenticated client from Actions secrets and run it."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify authentication and durable data without starting refreshes.",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Rebuild Spotify mirrors completely instead of merging recent changes.",
    )
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="Skip safely if GitHub starts the run outside the maintenance window.",
    )
    args = parser.parse_args(argv)
    try:
        space_url, hf_token, automation_token = required_environment()
        now = datetime.now(UTC)
        if args.scheduled and not scheduled_window_is_open(now):
            print(
                "Scheduled refresh started after the 05:00 Berlin deadline; "
                "skipping until the next maintenance window.",
                flush=True,
            )
            return 0
        client = SpaceClient(
            space_url,
            hf_token,
            automation_token,
            maintenance_deadline(now),
        )
        if args.check_only:
            return run_connection_check(client)
        jobs = FULL_REBUILD_JOBS if args.full_rebuild else JOBS
        freshness_threshold = maintenance_window_start(now) if args.scheduled else None
        return run_nightly_refresh(
            client,
            jobs,
            freshness_threshold=freshness_threshold,
        )
    except AutomationError as exc:
        print(f"::error::{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
