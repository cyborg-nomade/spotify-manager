"""Independent explicit application assembly for original nightly contracts."""

from datetime import UTC
from datetime import datetime
from functools import partial
from types import ModuleType
from zoneinfo import ZoneInfo

from spotify_manager.application import automation_run as workflow
from spotify_manager.application.automation_values import JOBS
from spotify_manager.application.automation_values import JobSpec
from spotify_manager.application.automation_values import refresh_jobs
from spotify_manager.infrastructure.automation_records import artifact_updates
from tests.support.automation_run import AutomationMemory


def emit(message: str) -> None:
    """Present original messages through the independently supplied output boundary.

    Args:
        message: Original visible progress text.
    """
    print(message, flush=True)


def fixed_now() -> datetime:
    """Observe the original deterministic cancellation clock.

    Returns:
        Original UTC instant.
    """
    return datetime(2026, 9, 24, tzinfo=UTC)


def cancel(client: AutomationMemory, spec: JobSpec, identity: str) -> None:
    """Inject original cancellation stages.

    Args:
        client: Recorded original API boundary.
        spec: Original cancellation route.
        identity: Original active handle.
    """
    workflow.cancel_job(client, spec, identity, fixed_now, emit)


def poll(client: AutomationMemory, spec: JobSpec, identity: str) -> str:
    """Inject polling and delayed cancellation explicitly.

    Args:
        client: Recorded original API boundary.
        spec: Original status route.
        identity: Original active handle.

    Returns:
        Original terminal outcome.
    """
    return workflow.poll_job(client, spec, identity, partial(cancel, client), emit)


def run_job(client: AutomationMemory, spec: JobSpec) -> str:
    """Inject original start and poll stages without script coordinators.

    Args:
        client: Recorded original API boundary.
        spec: Original job manifest entry.

    Returns:
        Original terminal outcome.
    """
    return workflow.run_job(
        client,
        spec,
        partial(workflow.start_job, client, emit=emit),
        partial(poll, client),
        emit,
    )


def fresh(client: AutomationMemory, threshold: datetime) -> bool:
    """Inject the original tolerant external timestamp parser.

    Args:
        client: Recorded original API boundary.
        threshold: Original inclusive freshness boundary.

    Returns:
        Original complete-artifact qualification.
    """
    return workflow.durable_artifacts_are_fresh(client, threshold, artifact_updates)


def run_automation(module: ModuleType, client: AutomationMemory) -> object:
    """Run every original workflow with independently supplied dependencies.

    Args:
        module: Original public error identities used by the boundary fake.
        client: Recorded original API boundary and profile.

    Returns:
        Original result without calling script coordinators.
    """
    spec = refresh_jobs(full_rebuild=False, scrobble_rebuild=True)[0]
    selected = client.scenario.workflow
    if selected == "start":
        return workflow.start_job(client, spec, emit)
    if selected == "poll":
        return poll(client, spec, "job")
    if selected == "connection":
        return workflow.connection_check(client, emit)
    if selected == "fresh":
        return fresh(client, datetime(2026, 9, 24, tzinfo=UTC))
    return workflow.nightly_refresh(
        client,
        JOBS,
        None,
        ZoneInfo("Europe/Berlin"),
        partial(fresh, client),
        partial(run_job, client),
        emit,
    )
