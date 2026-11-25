"""Publish a confirmed playlist with position-based recovery after a failed write."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from spotify_manager.domain.listening_export import SPOTIFY_BATCH_SIZE
from spotify_manager.domain.listening_export import AttemptedAppend
from spotify_manager.domain.listening_export import ExportPlan
from spotify_manager.domain.listening_export import ExportStage
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.domain.listening_export import PlaylistExportConflictError
from spotify_manager.domain.listening_export import SpotifyDestination
from spotify_manager.domain.listening_export import observed_append


class PlaylistServiceUnavailableError(RuntimeError):
    """A read failed or the provider explicitly rejected a retryable write."""


class PlaylistWriteRejectedError(RuntimeError):
    """The provider rejected the requested playlist change."""


class PlaylistGateway(Protocol):
    """Read owned destinations and issue individual Spotify mutations."""

    async def account(self) -> str:
        """Return the signed-in Spotify account."""
        ...

    async def destinations(self, account: str) -> tuple[SpotifyDestination, ...]:
        """List playlists owned by the account."""
        ...

    async def destination(self, identity: str) -> SpotifyDestination:
        """Read the playlist's owner, snapshot and total."""
        ...

    async def locate_created(
        self, account: str, marker: str
    ) -> SpotifyDestination | None:
        """Find the exact private playlist after a lost creation response."""
        ...

    async def create(
        self, target: ExportTarget, marker: str
    ) -> SpotifyDestination | None:
        """Create a private playlist once and retain an uncertain outcome."""
        ...

    async def append(self, playlist: str, uris: tuple[str, ...]) -> str | None:
        """Append one ordered batch once, returning its Spotify snapshot if known."""
        ...

    async def items(
        self, destination: SpotifyDestination, offset: int, count: int
    ) -> tuple[str | None, ...]:
        """Read a bounded stable slice of the playlist used for recovery."""
        ...


class PlaylistStop(Protocol):
    """Expose the owning job's safe cancellation signal."""

    def is_set(self) -> bool:
        """Return whether the worker should stop before the next write."""
        ...

    async def wait(self, timeout: float | None = None) -> bool:
        """Wait for cancellation or a bounded provider observation delay."""
        ...


@dataclass
class PlaylistExportJob:
    """Retain the plan and the known effects of attempts for the job lifetime."""

    job_id: str
    plan: ExportPlan
    stage: ExportStage = "prepared"
    message: str = ""
    added: int = 0
    playlist: SpotifyDestination | None = None
    creation_pending: bool = False
    pending: AttemptedAppend | None = None
    observed: int = 0

    @property
    def status(self) -> str:
        """Expose the phase to the shared task reservation helpers."""
        return self.stage

    @property
    def command(self) -> str:
        """Expose the export command identity."""
        return "listening_playlist_export"


async def run_playlist_export(
    job: PlaylistExportJob, gateway: PlaylistGateway, stop: PlaylistStop
) -> None:
    """Continue confirmed work from its verified destination and append position.

    Args:
        job: One previously reserved and confirmed export.
        gateway: Spotify resource that performs no blind retries of a write.
        stop: Shared job signal checked before each mutation and during waits.
    """
    job.stage = "running"
    try:
        if await gateway.account() != job.plan.target.account:
            raise PlaylistExportConflictError("The signed-in Spotify account changed.")
        await _run_export(job, gateway, stop)
    except PlaylistServiceUnavailableError as error:
        _pause(job, str(error))
    except (PlaylistExportConflictError, PlaylistWriteRejectedError) as error:
        job.stage, job.message = "failed", str(error)
    finally:
        if job.stage == "running":
            _pause(job, "The connection interrupted this export. Recheck its progress.")


async def _run_export(
    job: PlaylistExportJob, gateway: PlaylistGateway, stop: PlaylistStop
) -> None:
    if stop.is_set() and job.pending is None:
        _pause(job, "Paused before the next Spotify change.")
        return
    if not await _establish_playlist(job, gateway):
        _pause(
            job, "Spotify has not confirmed playlist creation. Recheck before retrying."
        )
        return
    while job.added < len(job.plan.tracks):
        if not await _advance(job, gateway, stop):
            return
    job.stage, job.message = "complete", "All confirmed tracks were added in order."


async def _establish_playlist(job: PlaylistExportJob, gateway: PlaylistGateway) -> bool:
    if job.playlist is not None:
        return True
    target = job.plan.target
    if target.existing is not None:
        job.playlist = target.existing
        return True
    marker = f"Spotify Manager export {job.job_id}"
    if not job.creation_pending:
        await _request_creation(job, gateway, marker)
    if job.playlist is None:
        job.playlist = await gateway.locate_created(target.account, marker)
    if job.playlist is None:
        return False
    if (
        job.playlist.count
        or job.playlist.owner != target.account
        or job.playlist.public
    ):
        raise PlaylistExportConflictError(
            "The newly created playlist does not match the preview."
        )
    job.creation_pending = False
    return True


async def _request_creation(
    job: PlaylistExportJob, gateway: PlaylistGateway, marker: str
) -> None:
    job.creation_pending = True
    try:
        job.playlist = await gateway.create(job.plan.target, marker)
    except PlaylistServiceUnavailableError, PlaylistWriteRejectedError:
        job.creation_pending = False
        raise


async def _advance(
    job: PlaylistExportJob, gateway: PlaylistGateway, stop: PlaylistStop
) -> bool:
    if job.pending is None:
        if stop.is_set():
            _pause(job, "Paused before adding the next group of tracks.")
            return False
        await _start_append(job, gateway, stop)
    if job.pending is None:
        _pause(job, "Paused before adding the next group of tracks.")
        return False
    for delay in (0.0, 0.4, 1.0, 2.0):
        if delay and await stop.wait(delay):
            break
        if await _observe(job, gateway):
            return True
    _pause(
        job,
        "Spotify has not confirmed the last group. Recheck before continuing.",
    )
    return False


async def _start_append(
    job: PlaylistExportJob, gateway: PlaylistGateway, stop: PlaylistStop
) -> None:
    assert job.playlist is not None
    current = await gateway.destination(job.playlist.identity)
    if current != job.playlist:
        raise PlaylistExportConflictError(
            "The destination changed. Review a new export before adding tracks."
        )
    if stop.is_set():
        return
    part = job.plan.tracks[job.added : job.added + SPOTIFY_BATCH_SIZE]
    attempt = AttemptedAppend(current.count, tuple(track.uri for track in part))
    job.pending = attempt
    try:
        receipt = await gateway.append(current.identity, attempt.uris)
    except PlaylistServiceUnavailableError, PlaylistWriteRejectedError:
        job.pending = None
        raise
    job.pending = replace(attempt, receipt=receipt)


async def _observe(job: PlaylistExportJob, gateway: PlaylistGateway) -> bool:
    assert job.playlist is not None and job.pending is not None
    attempt = job.pending
    current = await gateway.destination(job.playlist.identity)
    if (
        current.owner != job.plan.target.account
        or current.public != job.playlist.public
    ):
        raise PlaylistExportConflictError(
            "The destination’s access changed during the export."
        )
    count = max(0, min(len(attempt.uris), current.count - attempt.offset))
    items = await gateway.items(current, attempt.offset, count) if count else ()
    found = observed_append(attempt, current, items)
    job.observed = found
    if found < len(attempt.uris) and (not attempt.receipt or not found):
        return False
    job.added += found
    job.playlist, job.pending, job.observed = current, None, 0
    return True


def _pause(job: PlaylistExportJob, message: str) -> None:
    job.stage, job.message = "paused", message
