"""Await process-local job signals without blocking the web event loop."""

import asyncio
from dataclasses import dataclass
from dataclasses import field


@dataclass
class AsyncSignal:
    """Own one job's signal and accept notifications from HTTP delivery threads."""

    _event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)
    _set: bool = field(default=False, init=False)

    def is_set(self) -> bool:
        """Read the accepted signal state.

        Returns:
            Whether this signal is set.
        """
        return self._set

    def set(self) -> None:
        """Wake the owning loop after an accepted choice or cancellation."""
        self._set = True
        if self._loop is None:
            self._event.set()
            return
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._notify)

    def _notify(self) -> None:
        if self._set:
            self._event.set()

    def clear(self) -> None:
        """Clear a consumed submission on its owning loop."""
        self._set = False
        self._event.clear()

    async def wait(self, timeout: float | None = None) -> bool:
        """Await a signal or the original polling deadline.

        Args:
            timeout: Original maximum wait in seconds, or no deadline.

        Returns:
            Whether a signal was accepted before the deadline.
        """
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Job signal belongs to another event loop.")
        self._loop = loop
        if self._set:
            return True
        if timeout is not None and timeout <= 0:
            return False
        try:
            async with asyncio.timeout(timeout):
                await self._event.wait()
        except TimeoutError:
            return False
        return True
