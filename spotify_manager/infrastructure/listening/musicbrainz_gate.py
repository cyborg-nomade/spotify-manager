"""Share MusicBrainz request spacing across independent enrichment resources."""

import asyncio
import time


REQUEST_INTERVAL = 1.1


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
        """
        await self._lock.acquire()
        try:
            await asyncio.sleep(max(0, self._next_request - time.monotonic()))
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
