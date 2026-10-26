"""Retain the SDK's existing best-effort event-delivery boundary."""

import logging
from dataclasses import dataclass

from spotify_manager.application.ports.runtime import Messages


logger = logging.getLogger("spotify_manager.client")


@dataclass(frozen=True)
class SpotifyOutput:
    """Log and deliver the original credential diagnostics.

    Args:
        observer: Optional invocation-owned output.
    """

    observer: Messages | None

    def echo(self, message: str) -> None:
        """Retain the existing SDK boundary for best-effort display failures.

        Args:
            message: Safe diagnostic text without credential values.
        """
        logger.warning(message)
        if self.observer is None:
            return
        try:
            self.observer.echo(message)
        except Exception:  # Existing SDK display boundary, relocated without widening.
            logger.exception("Spotify event callback failed")
