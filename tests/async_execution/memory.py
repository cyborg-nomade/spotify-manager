"""Explicit barriers around original Requeue writes and complete namespace saves."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from threading import Event

from spotify_manager.application.music import NamedTrack
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.requeue import RequeueDependencies
from spotify_manager.application.requeue import flush_requeue
from spotify_manager.application.requeue_result import RequeueForADreamSummary
from spotify_manager.application.retry_attempts import CheckedAttempts
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.infrastructure.async_signal import AsyncSignal
from tests.application.test_requeue import MemoryRequeue


class StoppedAtBoundaryError(RuntimeError):
    """Signal the original post-acceptance cancellation boundary."""


@dataclass
class WriteBarrier:
    """Pause an external write before its accepted response.

    Args:
        entered: Observation that the request has started.
        release: Permission to return the accepted response.
    """

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class BarrierRequeue(MemoryRequeue):
    """Hold the original mutable playlist while one accepted write is outstanding.

    Args:
        barrier: Explicit request/response synchronization.
    """

    barrier: WriteBarrier = field(default_factory=WriteBarrier)

    async def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Return an accepted append only after the test releases its response.

        Args:
            playlist_id: Original destination.
            track: Original replacement marker.
        """
        self.barrier.entered.set()
        await self.barrier.release.wait()
        await super().append(playlist_id, track)


@dataclass(frozen=True)
class StopBoundary:
    """Observe cancellation at the retained retry scope's accepted boundary.

    Args:
        signal: Original job cancellation request.
    """

    signal: AsyncSignal

    def check(self) -> None:
        """Stop only after the current operation has returned its accepted response.

        Raises:
            StoppedAtBoundaryError: Cancellation was requested.
        """
        if self.signal.is_set():
            raise StoppedAtBoundaryError


@dataclass(frozen=True)
class CheckedPlaylists:
    """Use the production checked retry scopes around original playlist effects.

    Args:
        source: Mutable original playlist and effect recorder.
        stop: Job-owned cancellation boundary.
    """

    source: BarrierRequeue
    stop: StopBoundary

    async def sources(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read the original fresh playlist.

        Args:
            playlist_id: Destination identifier.

        Returns:
            Original ordered markers.
        """
        return await self.source.sources(playlist_id)

    async def append(self, playlist_id: str, track: NamedTrack) -> None:
        """Keep the original accepted-write cancellation check.

        Args:
            playlist_id: Destination identifier.
            track: Replacement marker.
        """
        self.stop.check()
        for scope in CheckedAttempts(NO_RETRY.attempts("append"), self.stop):
            async with scope:
                await self.source.append(playlist_id, track)

    async def remove(self, playlist_id: str, track: NamedTrack) -> None:
        """Remove only after preceding accepted scopes permit continuation.

        Args:
            playlist_id: Destination identifier.
            track: Original source marker.
        """
        self.stop.check()
        for scope in CheckedAttempts(NO_RETRY.attempts("remove"), self.stop):
            async with scope:
                await self.source.remove(playlist_id, track)

    def dependencies(self) -> RequeueDependencies:
        """Compose the actual application use case without SDKs or files.

        Returns:
            Original named ports and fixed observations.
        """
        return RequeueDependencies(
            self, self.source, self.source, None, self.source, self.source
        )


@dataclass
class RequeueJob:
    """Execute the actual use case and retain its original cancellation outcome.

    Args:
        playlists: Checked ordered playlist operations.
        stopped: Whether the original cancellation boundary was observed.
        summary: Successfully completed result, when present.
    """

    playlists: CheckedPlaylists
    stopped: bool = False
    summary: RequeueForADreamSummary | None = None

    async def run(self) -> None:
        """Run until completion or the original post-acceptance cancellation check."""
        try:
            self.summary = await flush_requeue(self.playlists.dependencies(), "queue")
        except StoppedAtBoundaryError:
            self.stopped = True


@dataclass
class BlockingState:
    """Hold a synchronous namespace write before its accepted commit.

    Args:
        entered: Worker-start observation.
        release: Permission to accept the write.
        value: Complete current namespace.
        events: Ordered store observations.
    """

    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    value: dict[str, object] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def load(self) -> dict[str, object]:
        """Read a detached namespace after acquiring the shared worker capacity.

        Returns:
            Complete accepted state.
        """
        self.events.append("read")
        return dict(self.value)

    def save(self, value: dict[str, object], *, message: str | None = None) -> object:
        """Accept a complete write only after its controlled response barrier.

        Args:
            value: Complete replacement namespace.
            message: Original optional provenance.

        Returns:
            Original unobserved acknowledgment.
        """
        self.events.append("write-started")
        self.entered.set()
        self.release.wait()
        self.value = dict(value)
        self.events.append("write-accepted")
        return None
