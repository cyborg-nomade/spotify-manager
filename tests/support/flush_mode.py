"""Typed external observations for Flush Mode policy and concurrency checks."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from spotify_manager.application.flush_mode import FlushModeCheckError
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.infrastructure.flush_mode_state import AsyncFlushModeState
from spotify_manager.infrastructure.flush_mode_state import FlushModeState
from spotify_manager.infrastructure.persistence.json_state_store import JsonStateStore


@dataclass(frozen=True)
class CheckClock:
    """Provide deterministic UTC check timestamps.

    Args:
        stamp: Aware UTC timestamp.
    """

    stamp: datetime

    def now(self) -> datetime:
        """Return the configured instant.

        Returns:
            Aware check timestamp.
        """
        return self.stamp


@dataclass
class CountObservation:
    """Delay or fail only the external count read.

    Args:
        counts: Complete successful observations.
        error: Optional concrete read failure.
        entered: Optional signal that the read has started.
        release: Optional signal allowing the read to finish.
    """

    counts: QueueCounts
    error: str | None = None
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None

    async def read(self) -> QueueCounts:
        """Read both scripted counts at a controlled external boundary.

        Returns:
            Complete observations.

        Raises:
            FlushModeCheckError: The configured read fails.
        """
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise FlushModeCheckError(self.error)
        return self.counts


def stored_mode(path: Path) -> AsyncFlushModeState:
    """Build real independent local persistence for a test.

    Args:
        path: Test-owned shared-state file.

    Returns:
        Real async state resource over central namespace persistence.
    """
    return AsyncFlushModeState(FlushModeState(StateService(JsonStateStore(path))))
