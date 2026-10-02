"""Capture original nightly job ordering, reconnection, deadlines and messages."""

import io
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.support.effects import Json
from tests.support.effects import encode_value


@dataclass(frozen=True)
class AutomationScenario:
    """Choose a workflow and decoded API response profile.

    Args:
        workflow: Original public coordinator.
        profile: Selected original response/failure.
    """

    workflow: str
    profile: str


def automation_scenarios() -> list[AutomationScenario]:
    """Enumerate original operational decisions and malformed responses.

    Returns:
        Stable original response matrix.
    """
    result = []
    for workflow in ("start", "poll", "run", "connection", "fresh"):
        for profile in (
            "normal",
            "invalid",
            "missing",
            "paused",
            "cancelled",
            "failed",
            "unknown",
            "lost",
            "blocked",
            "reconnect",
            "incompatible",
            "deadline",
            "stale",
            "naive",
            "bad-date",
            "duplicate",
            "malformed-row",
            "active",
        ):
            result.append(AutomationScenario(workflow, profile))
    return result


class FixedDatetime(datetime):
    """Retain the original public clock seam with a deterministic UTC instant."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FixedDatetime:
        """Observe the original fixed cancellation clock.

        Args:
            tz: Original timezone argument.

        Returns:
            Original deterministic UTC instant.
        """
        return cls(2026, 9, 24, 0, tzinfo=UTC)


class AutomationMemory:
    """Record original API observations through its unvalidated JSON boundary.

    Args:
        module: Loaded original script public interface.
        scenario: Selected response profile.
    """

    def __init__(self, module: ModuleType, scenario: AutomationScenario) -> None:
        """init  .

        Args:
            module: Loaded original automation script interface.
            scenario: Selected original workflow and raw response profile.
        """
        self.module = module
        self.scenario = scenario
        self.deadline = datetime(2026, 9, 24, 3, tzinfo=UTC)
        self.events: list[object] = []
        self.special_used = False
        self.polls = 0

    def request(self, method: str, path: str, **parameters: object) -> Any:
        """Return permissive external API values and original scripted failures.

        Args:
            method: Original HTTP verb.
            path: Original request path including query.
            parameters: Original retry and deadline flags.

        Returns:
            Unvalidated decoded external JSON.
        """
        self.events.append([method, path, parameters])
        if method == "POST":
            return self.post(path)
        if path.endswith("/job") or path.endswith("/existing"):
            return self.job_status()
        if path == "/library-mirrors/status":
            return self.artifacts()
        if path == "/state/summary":
            return {"revision": "sha"}
        if path == "/openapi.json":
            return {
                "paths": {
                    "/commands/one-jobs": {},
                    "/commands/two-jobs": {},
                    "/commands/one-jobs/{job_id}": {},
                }
            }
        if path.endswith("-jobs"):
            return [{"job_id": "active"}] if self.scenario.profile == "active" else []
        return {"status": "ok"}

    def post(self, path: str) -> object:
        """Post.

        Args:
            path: Original caller-supplied managed file location.

        Returns:
            Original post result.
        """
        if path.endswith("/cancel"):
            return {"status": "cancelling"}
        profile = self.scenario.profile
        if (
            profile in ("blocked", "reconnect", "incompatible")
            and not self.special_used
        ):
            self.special_used = True
            blocker = "unrelated" if profile == "blocked" else "update_scrobble_history"
            raise self.module.ApiError(
                409, {"detail": {"job_id": "existing", "command": blocker}}
            )
        if profile == "invalid":
            return None
        if profile == "missing":
            return {}
        return {"job_id": "job"}

    def job_status(self) -> object:
        profile = self.scenario.profile
        if profile == "incompatible" and self.polls == 0:
            self.polls += 1
            return {"history_full_rebuild": False, "dry_run": False}
        if profile == "reconnect":
            return {
                "history_full_rebuild": True,
                "dry_run": False,
                "status": "completed",
            }
        if profile == "lost" and not self.special_used:
            self.special_used = True
            raise self.module.ApiError(404, {"detail": "missing"})
        if profile == "invalid":
            return None
        if profile in ("missing", "paused", "cancelled", "failed", "unknown"):
            return {
                "status": "" if profile == "missing" else profile,
                "detail": "detail",
            }
        self.polls += 1
        return {
            "status": "running" if self.polls == 1 else "completed",
            "detail": "work",
        }

    def artifacts(self) -> object:
        profile = self.scenario.profile
        if profile == "invalid":
            return None
        if profile == "missing":
            return {"files": []}
        files: list[object] = []
        for name in sorted(self.module.DURABLE_ARTIFACT_FILENAMES):
            timestamp = "2026-09-24T01:00:00+00:00"
            if profile == "stale":
                timestamp = "2026-09-23T01:00:00+00:00"
            if profile == "naive":
                timestamp = "2026-09-24T01:00:00"
            if profile == "bad-date":
                timestamp = "bad"
            files.append({"filename": name, "exists": True, "updated_at": timestamp})
        if profile == "duplicate":
            files.append(
                {
                    "filename": "artists_total.json",
                    "exists": True,
                    "updated_at": "2026-09-23T01:00:00+00:00",
                }
            )
        if profile == "malformed-row":
            files[0] = None
        return {"files": files}

    def sleep(self, seconds: int) -> None:
        """Observe original retry/poll waits without blocking.

        Args:
            seconds: Original requested wait.
        """
        self.events.append(["sleep", seconds])

    def remaining_seconds(self) -> float:
        """Observe the selected original deadline.

        Returns:
            Original positive or exhausted remaining time.
        """
        return 0 if self.scenario.profile == "deadline" else 100


def execute(module: ModuleType, memory: AutomationMemory) -> object:
    """Execute.

    Args:
        module: Loaded original automation script interface.
        memory: Recorded original mutable boundary observations.

    Returns:
        Original execute result.
    """
    spec = module.refresh_jobs(full_rebuild=False, scrobble_rebuild=True)[0]
    workflow = memory.scenario.workflow
    if workflow == "start":
        return module.start_job(memory, spec)
    if workflow == "poll":
        return module.poll_job(memory, spec, "job")
    if workflow == "run":
        return module.run_nightly_refresh(memory)
    if workflow == "connection":
        return module.run_connection_check(memory)
    return module.durable_artifacts_are_fresh(memory, datetime(2026, 9, 24, tzinfo=UTC))


def observe_automation(
    module: ModuleType,
    scenario: AutomationScenario,
    run: Callable[[ModuleType, AutomationMemory], object] = execute,
) -> Json:
    """Capture original results, error causes, messages and all API requests.

    Args:
        module: Loaded original or compatibility script.
        scenario: Selected original workflow and profile.

    Returns:
        Immutable original observation.
    """
    memory = AutomationMemory(module, scenario)
    output = io.StringIO()
    with redirect_stdout(output):
        try:
            outcome: object = {"result": run(module, memory)}
        except (RuntimeError, AttributeError, TypeError, ValueError) as error:
            outcome = {
                "error": type(error).__name__,
                "message": str(error),
                "cause": type(error.__cause__).__name__ if error.__cause__ else None,
            }
    return encode_value(
        {"outcome": outcome, "events": memory.events, "output": output.getvalue()},
        Path("/tmp"),
    )
