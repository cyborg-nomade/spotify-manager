"""Named JSON Lines audit storage for Requeue outcomes."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.requeue_result import RequeueForADreamSummary


@dataclass(frozen=True)
class RequeueAudit:
    """Own the original audit file destination.

    Args:
        path: Explicit audit destination.
    """

    path: Path

    def write(self, result: RequeueForADreamSummary) -> None:
        """Accept a complete outcome with the original bytes and error semantics.

        Args:
            result: Complete routine outcome.
        """
        from spotify_manager.routines.requeue_for_a_dream import _append_log

        _append_log(result, self.path)
