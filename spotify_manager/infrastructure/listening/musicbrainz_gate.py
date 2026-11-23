"""Share MusicBrainz request spacing across independent enrichment resources."""

import asyncio
from asyncio import sleep
from time import monotonic

from spotify_manager.application.listening_provider_error import ListeningProviderError
from spotify_manager.infrastructure.listening.provider_retry import MAX_AUTOMATIC_WAIT
from spotify_manager.infrastructure.listening.provider_retry import MAX_RETRY_WAIT_TOTAL
from spotify_manager.infrastructure.listening.provider_retry import RETRY_DELAYS


REQUEST_INTERVAL = 1.1


class ProviderCooldownError(RuntimeError):
    """The provider requested a pause longer than the automatic wait budget."""


class MusicBrainzRequestGate:
    """Serialize request starts while retaining spacing across batches and views."""

    def __init__(self) -> None:
        """Initialize one application-owned provider gate."""
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def __aenter__(self) -> None:
        """Acquire a request slot while releasing ownership if waiting is cancelled.

        Raises:
            asyncio.CancelledError: The caller stops before a request starts.
            ProviderCooldownError: The provider asked to wait beyond the retry budget.
        """
        await self._lock.acquire()
        delay = self._next_request - monotonic()
        if delay > MAX_AUTOMATIC_WAIT:
            self._lock.release()
            raise ProviderCooldownError
        try:
            await sleep(max(0, delay))
        except asyncio.CancelledError:
            self._lock.release()
            raise

    async def __aexit__(self, *_exc: object) -> None:
        """Release only after the caller has drained its active provider read.

        Args:
            _exc: Context-manager exception details supplied by Python.
        """
        self._next_request = monotonic() + REQUEST_INTERVAL
        self._lock.release()

    def schedule_retry(
        self, error: ListeningProviderError, attempt: int, waited: float
    ) -> float | None:
        """Share provider cooldown with both views and limit single-item retries.

        Args:
            error: Sanitized failure classified at the transport boundary.
            attempt: One-based attempt that just failed.
            waited: Retry delay already scheduled for this item, in seconds.

        Returns:
            The next scheduled delay, or None when this item has stopped.
        """
        if not error.temporary:
            return None
        delay = max(
            RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)) - 1], error.retry_after
        )
        self._next_request = max(self._next_request, monotonic() + delay)
        if attempt > len(RETRY_DELAYS) or delay > MAX_AUTOMATIC_WAIT:
            return None
        if waited + delay > MAX_RETRY_WAIT_TOTAL:
            return None
        return delay
