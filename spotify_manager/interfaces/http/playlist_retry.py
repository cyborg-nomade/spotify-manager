"""Original bounded Spotify retry behavior with job-owned cancellation."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.retry_attempts import CheckedAttempts
from spotify_manager.application.retry_attempts import RetryAttempts
from spotify_manager.infrastructure.spotify.retry import SpotifyAttemptPolicy
from spotify_manager.infrastructure.spotify.retry import SpotifyRateLimitError
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass
class PlaylistRetry:
    """Keep retry callbacks attached to the original playlist job.

    Args:
        job: Existing handle owning the cancellation signal.
        output: Existing feature callback presenting retry notices.
    """

    job: PlaylistJob
    output: Messages

    def check(self) -> None:
        """Observe the original playlist retry cancellation boundary.

        Raises:
            blast_from_past.BlastFromPastCancelledError: Cancellation was requested.
        """
        blast_from_past.check_cancel(self.job.cancel_event)

    async def sleep(self, seconds: float) -> None:
        """Wait interruptibly on the existing cancellation signal.

        Args:
            seconds: Original retry delay.

        Raises:
            blast_from_past.BlastFromPastCancelledError: Cancellation interrupts.
        """
        if await self.job.cancel_event.wait(seconds):
            raise blast_from_past.BlastFromPastCancelledError(
                "Playlist routine cancelled."
            )

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        self.check()
        scopes = SpotifyRetries(self.output, self, 10, 3).attempts(description)
        return CheckedAttempts(scopes, self)


class RateLimitRecovery(Protocol):
    """Own a reconnectable job's rate-limit wait and accepted status."""

    async def wait_for_rate_limit(
        self, error: SpotifyRateLimitError, description: str
    ) -> None:
        """Wait at the original interface boundary.

        Args:
            error: Reported rate limit.
            description: Original operation description.
        """
        ...

    def retry_accepted(self) -> None:
        """Clear the original accepted retry status."""
        ...


@dataclass(frozen=True)
class RateLimitRetries:
    """Restart bounded transient attempts after an accepted rate-limit wait.

    Args:
        settings: Original bounded transport retry settings.
        owner: Job owning rate-limit waiting and presentation.
    """

    settings: SpotifyRetries
    owner: RateLimitRecovery

    def attempts(self, description: str) -> RetryAttempts:
        """Open a rate-limit-aware retry boundary without a deferred operation.

        Args:
            description: Original operation description.

        Returns:
            Scopes retaining the original transient counter reset after HTTP 429.
        """
        return RetryAttempts(
            RateLimitPolicy(
                self.settings.failure_policy(description), self.owner, description
            )
        )


@dataclass
class RateLimitPolicy:
    """Keep rate-limit recovery outside the bounded transient attempt policy.

    Args:
        transport: Original transient failure policy.
        owner: Job owning rate-limit waiting and presentation.
        description: Original operation description.
    """

    transport: SpotifyAttemptPolicy
    owner: RateLimitRecovery
    description: str

    def start(self) -> None:
        """Begin the original bounded request policy."""
        self.transport.start()

    def accepted(self) -> None:
        """Clear the job's retry status after accepting the request."""
        self.owner.retry_accepted()

    async def failed(self, error: BaseException) -> bool:
        """Wait for rate limits and preserve all other failure decisions.

        Args:
            error: Original request failure.

        Returns:
            Whether the operation should be attempted again.
        """
        try:
            return await self.transport.failed(error)
        except SpotifyRateLimitError as rate_limit:
            await self.owner.wait_for_rate_limit(rate_limit, self.description)
            self.transport.failures = 0
            return True
