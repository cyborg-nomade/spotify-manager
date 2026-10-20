"""Release-run clock observations and timestamp representations."""

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime


@dataclass(frozen=True)
class ReleaseClock:
    """Observe the original release clock at the opening boundary.

    Args:
        override: Optional caller-supplied effective instant.
    """

    override: datetime | None

    def clock(self) -> datetime:
        """Observe effective UTC time.

        Returns:
            Original supplied or current UTC instant.
        """
        from spotify_manager.routines import release_check as legacy

        return (self.override or legacy.datetime.now(UTC)).astimezone(UTC)

    def local_date(self, stamp: datetime) -> date:
        """Convert the observed timestamp to the original local date.

        Args:
            stamp: Effective UTC instant.

        Returns:
            Original local calendar date.
        """
        from spotify_manager.routines import release_check as legacy

        return stamp.astimezone(legacy.blast_from_past.SCROBBLE_TIMEZONE).date()

    def run_id(self, stamp: datetime) -> str:
        """Encode the observed timestamp as the original run identity.

        Args:
            stamp: Effective UTC instant.

        Returns:
            Original sortable identity.
        """
        from spotify_manager.routines.release_check import _run_id

        return _run_id(stamp)
