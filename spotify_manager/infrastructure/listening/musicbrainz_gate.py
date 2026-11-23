"""Share MusicBrainz request spacing across independent enrichment resources."""

import asyncio
import time

from spotify_manager.application.listening_provider_error import ListeningProviderError
from spotify_manager.infrastructure.listening.provider_retry import MAX_ATTEMPTS
from spotify_manager.infrastructure.listening.provider_retry import MAX_AUTOMATIC_WAIT


REQUEST_INTERVAL = 1.1
RETRY_BASE_SECONDS = 2


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
        delay = self._next_request - time.monotonic()
        if delay > MAX_AUTOMATIC_WAIT:
            self._lock.release()
            raise ProviderCooldownError
        try:
            await asyncio.sleep(max(0, delay))
        except asyncio.CancelledError:
            self._lock.release()
            raise

    async def __aexit__(self, *_exc: object) -> None:
        """Release only after the caller has drained its active provider read.

        Args:
            _exc: Context-manager exception details supplied by Python.
        """
        self._next_request = time.monotonic() + REQUEST_INTERVAL
        self._lock.release()

    def schedule_retry(self, error: ListeningProviderError, attempt: int) -> bool:
        """Share provider cooldown with both views and limit single-item retries.

        Args:
            error: Sanitized failure classified at the transport boundary.
            attempt: One-based attempt that just failed.

        Returns:
            Whether the failed item may be tried again in the current batch.
        """
        if not error.temporary:
            return False
        delay = max(RETRY_BASE_SECONDS * 2 ** (attempt - 1), error.retry_after)
        self._next_request = max(self._next_request, time.monotonic() + delay)
        return attempt < MAX_ATTEMPTS and delay <= MAX_AUTOMATIC_WAIT
