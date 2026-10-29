"""Preserve cancellation before and after each original annual retry boundary."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.retry_attempts import CheckedAttempts


@dataclass(frozen=True)
class AnnualRetry:
    """Bind original optional caller retry and explicit cancellation checks.

    Args:
        caller: Original optional retry boundary, tested for truthiness per call.
        cancel: Original cancellation check.
    """

    caller: RetryCall | None
    cancel: Cancellation

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        self.cancel.check()
        scopes = (self.caller or NoRetry()).attempts(description)
        return CheckedAttempts(scopes, self.cancel)
