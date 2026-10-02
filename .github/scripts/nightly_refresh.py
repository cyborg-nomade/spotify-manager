"""Compatibility entry point for the standard-library nightly refresh workflow."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast
from urllib.request import urlopen as urlopen
from zoneinfo import ZoneInfo


# Actions runs this file directly without installing the application package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spotify_manager.application import automation_run as workflow
from spotify_manager.application.automation_values import (
    ACTIVE_STATUSES as ACTIVE_STATUSES,
)
from spotify_manager.application.automation_values import (
    BLOCKED_RETRY_SECONDS as BLOCKED_RETRY_SECONDS,
)
from spotify_manager.application.automation_values import (
    DURABLE_ARTIFACT_FILENAMES as DURABLE_ARTIFACT_FILENAMES,
)
from spotify_manager.application.automation_values import (
    FULL_REBUILD_JOBS as FULL_REBUILD_JOBS,
)
from spotify_manager.application.automation_values import JOBS as JOBS
from spotify_manager.application.automation_values import (
    MANUAL_MAX_RUNTIME as MANUAL_MAX_RUNTIME,
)
from spotify_manager.application.automation_values import POLL_SECONDS as POLL_SECONDS
from spotify_manager.application.automation_values import (
    REQUEST_RETRY_SECONDS as REQUEST_RETRY_SECONDS,
)
from spotify_manager.application.automation_values import (
    TRANSIENT_HTTP_STATUSES as TRANSIENT_HTTP_STATUSES,
)
from spotify_manager.application.automation_values import ApiError as ApiError
from spotify_manager.application.automation_values import (
    AutomationError as AutomationError,
)
from spotify_manager.application.automation_values import (
    DeadlineReachedError as DeadlineReachedError,
)
from spotify_manager.application.automation_values import JobLostError as JobLostError
from spotify_manager.application.automation_values import JobSpec as JobSpec
from spotify_manager.application.automation_values import refresh_jobs as refresh_jobs
from spotify_manager.domain import automation_calendar as calendar
from spotify_manager.infrastructure.automation_http import OpenResponse
from spotify_manager.infrastructure.automation_http import SpaceHttpClient
from spotify_manager.infrastructure.automation_records import artifact_updates
from spotify_manager.infrastructure.automation_records import decode_response


DEFAULT_SPACE_URL = "https://cyborg-nomade-spotify-manager.hf.space"
BERLIN = ZoneInfo("Europe/Berlin")


class SpaceClient(SpaceHttpClient):
    """Retain the original script's transport, clock and credential entry points."""

    def __init__(
        self, space_url: str, hf_token: str, automation_token: str, deadline: datetime
    ) -> None:
        """Bind original script seams to the explicit urllib adapter.

        Args:
            space_url: Original Space URL.
            hf_token: Original private Space access token.
            automation_token: Original automation credential.
            deadline: Original maintenance boundary.
        """
        super().__init__(
            space_url,
            hf_token,
            automation_token,
            deadline,
            cast(OpenResponse, urlopen),
            _now,
            time.sleep,
            _emit,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _emit(message: str) -> None:
    print(message, flush=True)


def _decode_response(raw: bytes) -> object:
    return decode_response(raw)


def scrobble_rebuild_due(now: datetime) -> bool:
    """Select original Berlin monthly and New Year rebuild dates.

    Args:
        now: Original caller-owned instant.

    Returns:
        Original history rebuild qualification.
    """
    return calendar.scrobble_rebuild_due(now, BERLIN)


def maintenance_deadline(now: datetime) -> datetime:
    """Retain the original scheduled or manual run deadline.

    Args:
        now: Original caller-owned instant.

    Returns:
        Original UTC maintenance boundary.
    """
    return calendar.maintenance_deadline(now, BERLIN)


def scheduled_window_is_open(now: datetime) -> bool:
    """Retain the original Berlin maintenance-window check.

    Args:
        now: Original caller-owned instant.

    Returns:
        Original scheduled-run qualification.
    """
    return calendar.scheduled_window_is_open(now, BERLIN)


def maintenance_window_start(now: datetime) -> datetime:
    """Retain the original Berlin freshness boundary.

    Args:
        now: Original caller-owned instant.

    Returns:
        Original UTC window opening.
    """
    return calendar.maintenance_window_start(now, BERLIN)


def required_environment() -> tuple[str, str, str]:
    """Read original connection settings with unchanged missing-secret diagnostics.

    Returns:
        Original normalized URL and credentials.

    Raises:
        AutomationError: Original required credentials are absent.
    """
    space_url = os.environ.get("SPACE_URL", DEFAULT_SPACE_URL).rstrip("/") + "/"
    hf_token = os.environ.get("HF_SPACE_TOKEN", "").strip()
    automation_token = os.environ.get("AUTOMATION_TOKEN", "").strip()
    missing = []
    for name, value in (
        ("HF_SPACE_TOKEN", hf_token),
        ("AUTOMATION_TOKEN", automation_token),
    ):
        if not value:
            missing.append(name)
    if missing:
        raise AutomationError("Missing workflow secrets: " + ", ".join(missing))
    return space_url, hf_token, automation_token


def conflict_detail(error: ApiError) -> dict[str, object]:
    """Retain the original tolerant conflict detail view.

    Args:
        error: Original HTTP response failure.

    Returns:
        Original nested detail object.
    """
    return workflow.conflict_detail(error)


def start_job(client: workflow.SpaceAccess, spec: JobSpec) -> str:
    """Retain the original start and reconnect entry point.

    Args:
        client: Original caller-owned API client.
        spec: Original job manifest entry.

    Returns:
        Original accepted or reconnected identity.

    Raises:
        AutomationError: Original start or conflict handling fails.
    """
    return workflow.start_job(client, spec, _emit)


def cancel_job(client: workflow.SpaceAccess, spec: JobSpec, job_id: str) -> None:
    """Retain the original graceful cancellation entry point.

    Args:
        client: Original caller-owned API client.
        spec: Original cancellation route.
        job_id: Original active identity.

    Raises:
        AutomationError: Original cancellation fails outside tolerated statuses.
    """
    workflow.cancel_job(client, spec, job_id, _now, _emit)


def poll_job(client: workflow.SpaceAccess, spec: JobSpec, job_id: str) -> str:
    """Retain the original status, restart and deadline entry point.

    Args:
        client: Original caller-owned API client.
        spec: Original polling route.
        job_id: Original active identity.

    Returns:
        Original terminal outcome.

    Raises:
        AutomationError: Original polling or cancellation fails.
    """
    return workflow.poll_job(client, spec, job_id, partial(cancel_job, client), _emit)


def run_job(client: workflow.SpaceAccess, spec: JobSpec) -> str:
    """Retain original public start/poll seams and checkpoint resume behavior.

    Args:
        client: Original caller-owned API client.
        spec: Original job manifest entry.

    Returns:
        Original terminal outcome.
    """
    return workflow.run_job(
        client, spec, partial(start_job, client), partial(poll_job, client), _emit
    )


def run_nightly_refresh(
    client: workflow.SpaceAccess,
    jobs: tuple[JobSpec, ...] = JOBS,
    *,
    freshness_threshold: datetime | None = None,
) -> int:
    """Retain the original serial coordinator and public run-job seam.

    Args:
        client: Original caller-owned API client.
        jobs: Original ordered manifest.
        freshness_threshold: Original optional duplicate-trigger boundary.

    Returns:
        Original successful exit for completion, safe pause or deadline.
    """
    return workflow.nightly_refresh(
        client,
        jobs,
        freshness_threshold,
        BERLIN,
        partial(durable_artifacts_are_fresh, client),
        partial(run_job, client),
        _emit,
    )


def durable_artifacts_are_fresh(
    client: workflow.SpaceAccess, threshold: datetime
) -> bool:
    """Retain original decoded artifact observations and freshness decision.

    Args:
        client: Original caller-owned API client.
        threshold: Original inclusive window opening.

    Returns:
        Original all-artifacts qualification.
    """
    return workflow.durable_artifacts_are_fresh(client, threshold, artifact_updates)


def run_connection_check(client: workflow.SpaceAccess) -> int:
    """Retain original safe authentication, durable-state and active-job checks.

    Args:
        client: Original caller-owned API client.

    Returns:
        Original successful exit.

    Raises:
        AutomationError: An original prerequisite or active-job check fails.
    """
    return workflow.connection_check(client, _emit)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def _refresh(
    client: workflow.SpaceAccess, args: argparse.Namespace, now: datetime
) -> int:
    rebuild = scrobble_rebuild_due(now)
    jobs = refresh_jobs(full_rebuild=args.full_rebuild, scrobble_rebuild=rebuild)
    threshold = maintenance_window_start(now) if args.scheduled else None
    return run_nightly_refresh(
        client, jobs, freshness_threshold=None if rebuild else threshold
    )


def main(argv: list[str] | None = None) -> int:
    """Build the authenticated client from Actions secrets and run it.

    Args:
        argv: Original command-line arguments, or the process argument list.

    Returns:
        Original main result.
    """
    args = _arguments(argv)
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
        return _refresh(client, args, now)
    except AutomationError as exc:
        print(f"::error::{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
