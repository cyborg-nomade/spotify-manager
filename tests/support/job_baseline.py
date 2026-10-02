"""Observe the original job adapters without launching workers or touching data."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar
from typing import Literal
from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager import api
from spotify_manager.routines.release_check import ReleaseCheckPlaylists
from spotify_manager.routines.the_queue import QueuePlaylists
from tests.support.effects import FixedDatetime
from tests.support.effects import Json
from tests.support.effects import encode_value


type Result = api.AnalysisJobResult | api.BlastJobResult
type JobStatus = Literal[
    "queued",
    "running",
    "waiting",
    "cancelling",
    "cancelled",
    "paused",
    "completed",
    "failed",
]
type Family = Literal["analysis", "playlist"]
ROOT = Path(__file__).resolve().parents[2]
SPOTIFY = cast(Spotify, object())
QUEUE = QueuePlaylists("queue", "queue2", "kids", "queue3", "unlucky")
RELEASES = ReleaseCheckPlaylists("wine", "vintage")


@dataclass(frozen=True)
class StartCase:
    """Name one original adapter configuration and its registry.

    Args:
        name: Stable unique characterization identity.
        family: Original registry owning the job.
        start: Complete original start invocation with synthetic dependencies.
    """

    name: str
    family: Family
    start: Callable[[], Result]


CASES = (
    StartCase("analysis-async", "analysis", partial(api.start_analysis_job, "async")),
    StartCase(
        "analysis-sync", "analysis", partial(api.start_analysis_job, "sync", SPOTIFY)
    ),
    StartCase(
        "analysis-mirrors",
        "analysis",
        partial(api.start_analysis_job, "mirrors", SPOTIFY),
    ),
    StartCase(
        "mirror-albums",
        "analysis",
        partial(api.start_analysis_job, "mirrors", SPOTIFY, mirror_resource="albums"),
    ),
    StartCase(
        "mirror-tracks",
        "analysis",
        partial(api.start_analysis_job, "mirrors", SPOTIFY, mirror_resource="tracks"),
    ),
    StartCase(
        "mirror-artists",
        "analysis",
        partial(
            api.start_analysis_job,
            "mirrors",
            SPOTIFY,
            mirror_resource="artists",
            full_rebuild=True,
        ),
    ),
    StartCase(
        "blast",
        "playlist",
        partial(api.start_blast_job, SPOTIFY, "playlist", 5, None, False),
    ),
    StartCase(
        "dormant",
        "playlist",
        partial(api.start_blast_artist_job, SPOTIFY, "playlist", 5, True),
    ),
    StartCase(
        "daily",
        "playlist",
        partial(api.start_daily_mind_radio_job, SPOTIFY, "playlist", False),
    ),
    StartCase(
        "found",
        "playlist",
        partial(api.start_found_art_job, SPOTIFY, "playlist", "key", "user", 20),
    ),
    StartCase(
        "sauvignon",
        "playlist",
        partial(
            api.start_sauvignon_job,
            SPOTIFY,
            "playlist",
            "key",
            "user",
            count=5,
            max_playlist_length=None,
            seed_count=30,
            dry_run=True,
        ),
    ),
    StartCase(
        "queue-fill",
        "playlist",
        partial(
            api.start_queue_fill_job,
            SPOTIFY,
            QUEUE,
            "key",
            "user",
            count=None,
            max_playlist_length=50,
            seed_count=30,
            dry_run=False,
        ),
    ),
    StartCase(
        "queue-flush",
        "playlist",
        partial(api.start_queue_flush_job, SPOTIFY, QUEUE, dry_run=True),
    ),
    StartCase(
        "new-kids",
        "playlist",
        partial(
            api.start_new_kids_job,
            SPOTIFY,
            "kids",
            "queue2",
            "discoveries",
            "unlucky",
            "newfoundland",
            dry_run=False,
        ),
    ),
    StartCase(
        "queue2",
        "playlist",
        partial(
            api.start_queue_2_job,
            SPOTIFY,
            "kids",
            "queue2",
            "discoveries",
            "unlucky",
            "newfoundland",
            dry_run=True,
        ),
    ),
    StartCase(
        "queue3",
        "playlist",
        partial(api.start_queue_3_job, SPOTIFY, "playlist", dry_run=False),
    ),
    StartCase(
        "queue3-import",
        "playlist",
        partial(
            api.start_queue_3_job, SPOTIFY, "playlist", dry_run=True, annual_only=True
        ),
    ),
    StartCase(
        "new-wine",
        "playlist",
        partial(
            api.start_new_wine_job,
            SPOTIFY,
            "wine",
            "sauvignon",
            "cellar",
            dry_run=False,
            no_discovery=True,
            choose_album_endpoints=True,
        ),
    ),
    StartCase(
        "slow",
        "playlist",
        partial(api.start_slow_listening_job, SPOTIFY, "playlist", dry_run=True),
    ),
    StartCase(
        "old",
        "playlist",
        partial(
            api.start_something_old_job,
            SPOTIFY,
            "playlist",
            "key",
            "user",
            dry_run=False,
        ),
    ),
    StartCase(
        "releases",
        "playlist",
        partial(
            api.start_release_check_job, SPOTIFY, RELEASES, "key", "user", dry_run=True
        ),
    ),
    StartCase(
        "discography",
        "playlist",
        partial(
            api.start_discography_job,
            SPOTIFY,
            {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"},
            "queue3",
            dry_run=False,
        ),
    ),
    StartCase(
        "requeue",
        "playlist",
        partial(api.start_requeue_for_a_dream_job, SPOTIFY, "playlist", dry_run=True),
    ),
    StartCase(
        "palace",
        "playlist",
        partial(
            api.start_palace_of_memory_job,
            SPOTIFY,
            "playlist",
            dry_run=False,
            alphabetical_start="Artist",
            cursor_position=None,
        ),
    ),
    StartCase(
        "palace-cursor",
        "playlist",
        partial(
            api.start_palace_of_memory_job,
            SPOTIFY,
            None,
            dry_run=True,
            alphabetical_start=None,
            cursor_position=50,
        ),
    ),
    StartCase(
        "history",
        "playlist",
        partial(
            api.start_scrobble_history_job,
            "key",
            "user",
            dry_run=False,
            full_rebuild=True,
        ),
    ),
    StartCase(
        "annual",
        "playlist",
        partial(api.cmd_new_year, SPOTIFY, dry_run=True, year=2025),
    ),
)
STATUSES: tuple[JobStatus, ...] = (
    "queued",
    "running",
    "waiting",
    "cancelling",
    "cancelled",
    "paused",
    "completed",
    "failed",
)


@dataclass
class Identities:
    """Generate deterministic, distinct original UUID handles.

    Args:
        count: Number of accepted identity observations.
    """

    count: int = 0

    def __call__(self) -> UUID:
        """Allocate the next synthetic UUID.

        Returns:
            Original UUID shape with a stable increasing value.
        """
        self.count += 1
        return UUID(int=self.count)


@dataclass
class ThreadCapture:
    """Replace a worker launch while checking registration preceded dispatch.

    Args:
        target: Original worker callback.
        args: Original ordered worker arguments.
        name: Original diagnostic thread name.
        daemon: Original thread lifetime flag.
    """

    target: Callable[..., object]
    args: tuple[object, ...]
    name: str
    daemon: bool
    observations: ClassVar[list[dict[str, Json]]] = []

    def start(self) -> None:
        """Record an accepted launch without invoking the worker.

        Raises:
            AssertionError: The job was not registered before dispatch.
        """
        identifier = str(self.args[0])
        registered = identifier in api._blast_jobs or identifier in api._analysis_jobs
        assert registered
        self.observations.append(
            {
                "worker": self.target.__name__,
                "args": _arguments(self.args),
                "name": self.name,
                "daemon": self.daemon,
            }
        )


def _arguments(values: tuple[object, ...]) -> list[Json]:
    result: list[Json] = []
    for value in values:
        result.append("<spotify>" if value is SPOTIFY else encode_value(value, ROOT))
    return result


def reset() -> None:
    """Clear only the synthetic process-local registries and captured dispatches."""
    with api._analysis_jobs_lock:
        api._analysis_jobs.clear()
    with api._blast_jobs_lock:
        api._blast_jobs.clear()
    ThreadCapture.observations.clear()


def bind(patch: pytest.MonkeyPatch) -> None:
    """Supply deterministic clocks, handles and synthetic worker dispatch.

    Args:
        patch: Scope owning the replacement lifetime.
    """
    reset()
    patch.setattr(api, "Thread", ThreadCapture)
    patch.setattr(api, "uuid4", Identities())
    patch.setattr(api, "datetime", FixedDatetime)


def queued(case: StartCase) -> dict[str, Json]:
    """Observe the complete queued snapshot and original scheduler arguments.

    Args:
        case: Original configured start adapter.

    Returns:
        Detached JSON-compatible original observations.
    """
    with pytest.MonkeyPatch.context() as patch:
        bind(patch)
        snapshot = case.start()
        return {
            "snapshot": cast(Json, snapshot.model_dump(mode="json")),
            "launches": encode_value(ThreadCapture.observations, ROOT),
        }


def conflict(first: StartCase, second: StartCase, status: JobStatus) -> dict[str, Json]:
    """Observe the original asymmetric conflict rules without running a routine.

    Args:
        first: Previously registered adapter.
        second: Requested subsequent adapter.
        status: Previously observed job phase.

    Returns:
        Accepted command/dispatch counts or exact original HTTP conflict details.
    """
    with pytest.MonkeyPatch.context() as patch:
        bind(patch)
        existing = first.start()
        _set_status(first, existing.job_id, status)
        return _attempt(second)


def _set_status(case: StartCase, identifier: str, status: JobStatus) -> None:
    if case.family == "analysis":
        api._analysis_jobs[identifier].result.status = status
        return
    api._blast_jobs[identifier].result.status = status


def _attempt(case: StartCase) -> dict[str, Json]:
    try:
        result = case.start()
    except HTTPException as error:
        return {"status_code": error.status_code, "detail": cast(Json, error.detail)}
    return {
        "status_code": 202,
        "command": result.command,
        "launches": len(ThreadCapture.observations),
    }


def pair_cases() -> list[tuple[StartCase, StartCase]]:
    """Enumerate the original directed overlap matrix.

    Returns:
        Every ordered pair of registered and requested adapters.
    """
    result = []
    for first in CASES:
        for second in CASES:
            result.append((first, second))
    return result


def capture() -> dict[str, Json]:
    """Freeze start, overlap and phase observations before production changes.

    Returns:
        Complete original job protocol observation tables.
    """
    starts: dict[str, Json] = {}
    pairs: dict[str, Json] = {}
    phases: dict[str, Json] = {}
    for case in CASES:
        starts[case.name] = queued(case)
        for status in STATUSES:
            phases[f"{case.name}:{status}"] = conflict(case, case, status)
    for first, second in pair_cases():
        pairs[f"{first.name}:{second.name}"] = conflict(first, second, "running")
    reset()
    return {
        "source": "93a36aa79567b54a5907d324af444a049136a532",
        "starts": starts,
        "pairs": pairs,
        "phases": phases,
    }
