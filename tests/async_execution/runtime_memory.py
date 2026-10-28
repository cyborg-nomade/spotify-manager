"""Named barriers and observers for invocation resource ownership tests."""

import asyncio
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.bootstrap.spotify_async import AsyncSpotifyRuntime
from spotify_manager.client.events import SpotifyOutput
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.settings import Settings
from tests.spotify_async.memory import OutputMemory


@dataclass
class ConstructionGate:
    """Hold resource construction while shutdown tries to acquire ownership."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def open(self) -> AsyncSpotifyRuntime:
        """Return a real owner only after the construction barrier is released.

        Returns:
            Native owner whose OAuth provisioning is isolated by the test.
        """
        self.entered.set()
        await self.release.wait()
        return AsyncSpotifyRuntime(Settings())


@dataclass(frozen=True)
class ObservedEvents:
    """Overlap subscriptions while retaining distinct invocation output contexts.

    Args:
        client: Shared native client with no mutable job callback.
        barrier: Rendezvous after both subscriptions have been established.
        output: This invocation's diagnostic observations.
        label: Distinct safe diagnostic text.
    """

    client: AsyncSpotify
    barrier: asyncio.Barrier
    output: OutputMemory
    label: str

    async def run(self) -> None:
        """Observe only this task's subscription despite shared transport ownership."""
        events = SpotifyEvents(self.client)
        events.subscribe(self.output)
        try:
            await self.barrier.wait()
            SpotifyOutput(None).echo(self.label)
        finally:
            events.restore()


class InterruptedWorker:
    """Expose a process-control failure at the background task ownership boundary."""

    async def run(self) -> None:
        """Raise the control failure that previously terminated only its worker thread.

        Raises:
            SystemExit: Simulated worker-local process-control exception.
        """
        raise SystemExit("worker stopped")
