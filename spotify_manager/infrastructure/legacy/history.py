"""Last.fm history adapter retaining all original export fallbacks."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import blast_from_past


@dataclass(frozen=True)
class ExportListeningHistory:
    """Read the configured export through its existing tolerant loader.

    Args:
        path: Explicit export location, including its supported compressed fallbacks.
    """

    path: Path

    def by_date(self) -> dict[date, tuple[Scrobble, ...]]:
        """Load the original Berlin-local buckets and event ordering.

        Returns:
            Typed scrobbles, retaining the loader's timezone and tie semantics.

        Raises:
            blast_from_past.LastFmExportError: The export cannot be read or parsed.
        """
        result = {}
        for day, scrobbles in blast_from_past.load_scrobbles_by_date(self.path).items():
            result[day] = tuple(scrobbles)
        return result
