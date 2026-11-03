"""Verify original retry exhaustion, error reporting and partial undo behavior."""

from collections import deque
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout
from spotipy.exceptions import SpotifyException

from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import LibrarySyncRestoreError
from spotify_manager.domain.library_analysis_values import RetryNotice
from spotify_manager.infrastructure import library_analysis_backups as backups
from spotify_manager.infrastructure.library_analysis_errors import AnalysisFailure
from spotify_manager.infrastructure.library_analysis_restore import restore_library_sync
from spotify_manager.infrastructure.library_analysis_retry import LibraryRetry
from tests.application.library_analysis_memory import AnalysisMemory
from tests.application.library_analysis_memory import memory_session


@dataclass
class RetryScript:
    """Supply ordered external failures and record original wait observations.

    Args:
        responses: Original ordered returned facts or raised external failures.
        decision: Original optional interactive retry choice.
        notices: Original complete interactive retry notices.
        delays: Original default blocking wait observations.
    """

    responses: deque[object]
    decision: bool = True
    notices: list[RetryNotice] = field(default_factory=list)
    delays: list[float] = field(default_factory=list)

    def call(self) -> object:
        """Observe the original next accepted or failed request.

        Returns:
            Original accepted response.

        Raises:
            BaseException: The configured original transport failure.
        """
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response

    async def wait(self, notice: RetryNotice) -> bool:
        """Record the original interactive retry decision.

        Args:
            notice: Original complete retry details.

        Returns:
            Original continue-versus-pause choice.
        """
        self.notices.append(notice)
        return self.decision

    async def sleep(self, delay: float) -> None:
        """Observe original default waits, including zero delays.

        Args:
            delay: Original requested blocking delay.
        """
        self.delays.append(delay)


async def _read(
    retry: LibraryRetry, script: RetryScript, maximum: int | None = None
) -> object:
    for attempt in retry.attempts("reading facts", max_attempts=maximum):
        async with attempt:
            response = script.call()
    return response


def _error(status: int | None) -> SpotifyException:
    return SpotifyException(status, -1, "original failure")


@pytest.mark.parametrize("status", [None, 403])
async def test_nontransient_failures_keep_type_cause_and_skip_retry(
    tmp_path: Path, status: int | None
) -> None:
    """Preserve nontransient failure translation without waiting.

    Args:
        tmp_path: Original independent output family.
        status: Original terminal Spotify status.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    failure = _error(status)
    script = RetryScript(deque([failure]))
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        script,
        script,
        10,
        100,
    )
    with pytest.raises(LibrarySyncError) as observed:
        await _read(retry, script)
    assert observed.value.__cause__ is failure
    assert script.notices == []
    assert memory.effects == []


@pytest.mark.parametrize("interactive", [False, True])
async def test_repeated_rate_limits_retry_the_same_request_until_success(
    tmp_path: Path, interactive: bool
) -> None:
    """Wait through repeated cooldowns independently of transient attempt limits.

    Args:
        tmp_path: Isolated checkpoint and audit paths.
        interactive: Whether a web-style cancellable wait is supplied.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    failures = []
    expected = []
    for index, delay in enumerate((90, 7200, 3, 1), start=1):
        failures.append(
            SpotifyException(429, -1, "limited", headers={"Retry-After": str(delay)})
        )
        expected.append(RetryNotice(429, "reading facts", index, delay))
    script = RetryScript(deque([*failures, "accepted"]))
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        script if interactive else None,
        script,
        10,
        100,
    )
    assert await _read(retry, script, maximum=1) == "accepted"
    assert script.notices == (expected if interactive else [])
    assert script.delays == ([] if interactive else [90, 7200, 3, 1])
    events = [name for name, _value in memory.effects]
    assert events == ["rate_limit_retry_scheduled", "echo"] * 4


async def test_rate_limit_without_header_uses_increasing_fallback_wait(
    tmp_path: Path,
) -> None:
    """Keep malformed and absent deadlines from causing immediate retries.

    Args:
        tmp_path: Isolated checkpoint and audit paths.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    malformed = SpotifyException(429, -1, "limited", headers={"Retry-After": "later"})
    script = RetryScript(deque([_error(429), malformed, "accepted"]))
    retry = LibraryRetry(
        session.paths, session.checkpoint, session.files, memory, script, script, 0, 0
    )
    assert await _read(retry, script) == "accepted"
    assert script.notices == [
        RetryNotice(429, "reading facts", 1, 60),
        RetryNotice(429, "reading facts", 2, 120),
    ]


async def test_server_attempt_limit_keeps_last_failure_and_accepted_retry(
    tmp_path: Path,
) -> None:
    """Retain original bounded retries and omit a wait after the terminal attempt.

    Args:
        tmp_path: Original independent output family.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    failures = [_error(500), _error(503)]
    script = RetryScript(deque(failures))
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        script,
        script,
        10,
        100,
    )
    with pytest.raises(
        LibrarySyncError, match="HTTP 503 persisted for 2 attempts"
    ) as observed:
        await _read(retry, script, 2)
    assert observed.value.__cause__ is failures[-1]
    assert script.notices == [RetryNotice(500, "reading facts", 1, 10)]
    assert script.delays == []


@pytest.mark.parametrize(
    "failure", [RequestsConnectionError("reset"), RequestsTimeout("timeout")]
)
async def test_transport_attempt_limit_does_not_retry_after_its_bound(
    tmp_path: Path, failure: RequestsConnectionError | RequestsTimeout
) -> None:
    """Retain original bounded transport exhaustion and native cause.

    Args:
        tmp_path: Original independent output family.
        failure: Original transport failure.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    script = RetryScript(deque([failure]))
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        script,
        script,
        10,
        100,
    )
    with pytest.raises(
        LibrarySyncError, match="connection remained unavailable for 1 attempts"
    ) as observed:
        await _read(retry, script, 1)
    assert observed.value.__cause__ is failure
    assert memory.effects == []


async def test_default_retry_wait_observes_zero_sleep_and_shared_failure(
    tmp_path: Path,
) -> None:
    """Keep original default zero waits and mixed server/transport attempt numbering.

    Args:
        tmp_path: Original independent output family.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    script = RetryScript(
        deque([_error(500), RequestsConnectionError("reset"), "accepted"])
    )
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        None,
        script,
        0,
        100,
    )
    assert await _read(retry, script) == "accepted"
    assert script.delays == [0, 0]
    assert [name for name, _value in memory.effects] == [
        "server_retry_scheduled",
        "echo",
        "transport_retry_scheduled",
        "echo",
    ]


@pytest.mark.parametrize(
    "failure", [_error(429), _error(500), RequestsConnectionError("reset")]
)
async def test_retry_wait_cancellation_retains_original_error_cause(
    tmp_path: Path, failure: BaseException
) -> None:
    """Keep original interactive cancellation after its accepted retry audit.

    Args:
        tmp_path: Original independent output family.
        failure: Original server or transport failure.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    script = RetryScript(deque([failure]), decision=False)
    retry = LibraryRetry(
        session.paths,
        session.checkpoint,
        session.files,
        memory,
        script,
        script,
        10,
        100,
    )
    with pytest.raises(
        LibraryAnalysisCancelledError, match="paused during a Spotify retry wait"
    ) as observed:
        await _read(retry, script)
    assert observed.value.__cause__ is failure
    assert len(script.notices) == 1


async def test_system_exit_retains_original_propagation_without_audit(
    tmp_path: Path,
) -> None:
    """Retain original propagation for process-control errors outside ordinary failures.

    Args:
        tmp_path: Original independent output family.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    with pytest.raises(SystemExit):
        async with AnalysisFailure(
            session, "failed", (LibraryAnalysisCancelledError, KeyboardInterrupt)
        ):
            raise SystemExit(4)
    assert memory.effects == []


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        {"targets": {"stats_history": {"existed": True, "backup_file": "before.json"}}},
    ],
)
async def test_backed_up_history_retains_original_shape_failures(
    tmp_path: Path, manifest: object
) -> None:
    """Keep original invalid manifest and backed-up history errors.

    Args:
        tmp_path: Original independent output family.
        manifest: Original missing or valid manifest referencing malformed history.
    """
    memory = AnalysisMemory(
        raw={tmp_path / "manifest.json": manifest, tmp_path / "before.json": "invalid"}
    )
    session = await memory_session(memory, tmp_path)
    with pytest.raises(LibrarySyncError, match="invalid"):
        (backups.pre_analysis_stats_history(session.paths, tmp_path, memory))


async def test_absent_backed_up_history_is_empty_without_reading_another(
    tmp_path: Path,
) -> None:
    """Keep original history absence semantics when the analysis created that output.

    Args:
        tmp_path: Original independent output family.
    """
    manifest = {"targets": {"stats_history": {"existed": False}}}
    memory = AnalysisMemory(raw={tmp_path / "manifest.json": manifest})
    session = await memory_session(memory, tmp_path)
    assert (backups.pre_analysis_stats_history(session.paths, tmp_path, memory)) == {}
    assert memory.effects == [("read", tmp_path / "manifest.json")]


def _publish(path: Path, source: str) -> None:
    assert path.is_file()


@pytest.mark.parametrize("run_id", ["", "../run", "run/name", "run\\name", "run..name"])
async def test_restore_rejects_original_invalid_run_ids_before_reading(
    tmp_path: Path, run_id: str
) -> None:
    """Retain original path-component rejection, including embedded double dots.

    Args:
        tmp_path: Original independent output family.
        run_id: Original unusable requested identity.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    with pytest.raises(
        LibrarySyncRestoreError, match="Invalid library-analysis run id"
    ):
        (restore_library_sync(run_id, [session.paths], memory))
    assert memory.effects == []


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        {"run_id": "wrong"},
        {"run_id": "requested", "targets": None},
        {
            "run_id": "requested",
            "targets": {"albums": {"existed": True, "backup_file": "missing"}},
        },
    ],
)
async def test_restore_retains_missing_manifest_target_and_backup_errors(
    tmp_path: Path, manifest: object
) -> None:
    """Keep original first-match selection and missing undo-file failures.

    Args:
        tmp_path: Original independent output family.
        manifest: Original unusable undo data.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    path = session.paths.backups_dir / "requested/manifest.json"
    memory.raw[path] = manifest
    with pytest.raises(LibrarySyncRestoreError):
        (restore_library_sync("requested", [session.paths], memory))


async def test_restore_skips_unknown_targets_and_removes_outputs_absent(
    tmp_path: Path,
) -> None:
    """Retain original manifest encounter order and deletion of newly created outputs.

    Args:
        tmp_path: Original independent output family.
    """
    memory = AnalysisMemory()
    session = await memory_session(memory, tmp_path)
    path = session.paths.backups_dir / "requested/manifest.json"
    memory.raw[path] = {
        "run_id": "requested",
        "targets": {"unknown": {}, "tracks": None, "albums": {"existed": False}},
    }
    session.paths.albums_total.write_text("new output")
    assert (restore_library_sync("requested", [session.paths], memory)) == (
        session.paths.albums_total.name,
    )
    assert not session.paths.albums_total.exists()
    assert memory.effects[-1][0] == "run_restored"
