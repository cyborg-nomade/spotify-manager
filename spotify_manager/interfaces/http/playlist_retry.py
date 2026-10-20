"""Original bounded Spotify retry behavior with job-owned cancellation."""

from collections.abc import Callable
from dataclasses import dataclass

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
        echo: Existing feature callback presenting retry notices.
    """

    job: PlaylistJob
    echo: Callable[[str], None]

    def sleep(self, seconds: float) -> None:
        """Wait interruptibly on the existing cancellation signal.

        Args:
            seconds: Original retry delay.

        Raises:
            blast_from_past.BlastFromPastCancelledError: Cancellation interrupts.
        """
        if self.job.cancel_event.wait(seconds):
            raise blast_from_past.BlastFromPastCancelledError(
                "Playlist routine cancelled."
            )

    def call(self, operation: Callable[[], object], description: str) -> object:
        """Retry up to three times with the original safe cancellation boundaries.

        Args:
            operation: Original SDK request or routine operation.
            description: Existing retry notice text.

        Returns:
            Original successful operation result.

        Raises:
            blast_from_past.BlastFromPastCancelledError: A safe boundary stops.
            review_album_limits.SpotifyRateLimitError: Spotify asks to pause.
            review_album_limits.SpotifyTransientServerError: Retries are exhausted.
        """
        blast_from_past.check_cancel(self.job.cancel_event.is_set)
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self.echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        blast_from_past.check_cancel(self.job.cancel_event.is_set)
        return result
