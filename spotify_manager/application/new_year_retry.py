"""Preserve cancellation before and after each original annual retry boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.new_year_membership import RetryCall


@dataclass(frozen=True)
class AnnualRetry:
    """Bind original optional caller retry and explicit cancellation checks.

    Args:
        caller: Original optional retry boundary, tested for truthiness per call.
        cancel: Original cancellation check.
    """

    caller: RetryCall | None
    cancel: Callable[[], None]

    def run(self, operation: Callable[[], object], description: str) -> object:
        """Check cancellation around the complete original caller-owned operation.

        Args:
            operation: Original complete deferred read or effect.
            description: Original retry description.

        Returns:
            Original accepted operation result.
        """
        self.cancel()
        result = self.caller(operation, description) if self.caller else operation()
        self.cancel()
        return result
