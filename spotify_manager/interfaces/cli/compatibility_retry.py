"""Retain the original synchronous terminal retry API at the Python boundary."""

import select
import sys
import termios
import tty
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta

from rich.console import Console
from rich.live import Live
from rich.progress import Progress
from spotipy import Spotify

from spotify_manager.application.ports.runtime import BlockingWait
from spotify_manager.application.ports.runtime import MonotonicClock
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.operations import analyse_library as library_sync


@dataclass(frozen=True)
class BlockingAnalysisRetry:
    """Own unchanged synchronous operator input for retained Python callers.

    Native commands use AnalysisCLI's awaited choices and retry delays. This
    compatibility owner never runs inside the web or native command execution.

    Args:
        display: Original Rich text construction resources.
        create_live: Original Rich live-display constructor.
        monotonic: Original elapsed-time observer.
        sleep: Original synchronous retry delay owner.
    """

    display: ConsoleDisplay
    create_live: type[Live]
    monotonic: MonotonicClock
    sleep: BlockingWait

    def wait(
        self,
        console: Console,
        notice: library_sync.RetryNotice,
        spotify: Spotify,
        progress: Progress | None,
    ) -> bool:
        """Wait for a retry while accepting rotate or quit without Enter.

        Args:
            console: Rich console receiving this command's output.
            notice: Notice supplied by the caller.
            spotify: Spotify supplied by the caller.
            progress: Active progress display to suspend while prompting.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if progress is not None:
            progress.stop()
        self._show_retry_notice(console, notice)
        try:
            if not sys.stdin.isatty():
                self.sleep.sleep(notice.delay_seconds)
                return True
            return self._wait_terminal_retry(console, spotify, notice.delay_seconds)
        finally:
            if progress is not None:
                progress.start()

    def _show_retry_notice(
        self, console: Console, notice: library_sync.RetryNotice
    ) -> None:
        retry_at = datetime.now().astimezone() + timedelta(seconds=notice.delay_seconds)
        failure = (
            f"Spotify HTTP {notice.http_status}"
            if notice.http_status is not None
            else "Spotify connection interrupted"
        )
        console.print(f"{failure} while {notice.operation}.", style="bold yellow")
        console.print(
            (
                f"Retry {notice.attempt} at "
                f"{retry_at.isoformat(timespec='seconds')}"
                f". Press r to rotate credentials and retry now, or q to save "
                f"and quit."
            ),
            style="yellow",
        )

    def _wait_terminal_retry(
        self, console: Console, spotify: Spotify, delay: float
    ) -> bool:
        """Wait terminal retry.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.
            delay: Delay supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        descriptor = sys.stdin.fileno()
        old_settings = termios.tcgetattr(descriptor)
        deadline = self.monotonic.monotonic() + delay
        try:
            tty.setcbreak(descriptor)
            with self.create_live(
                console=console, refresh_per_second=2, transient=True
            ) as live:
                return self._read_retry_keys(console, spotify, deadline, live)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, old_settings)

    def _read_retry_keys(
        self, console: Console, spotify: Spotify, deadline: float, live: Live
    ) -> bool:
        """Read retry keys.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.
            deadline: Deadline supplied by the caller.
            live: Live supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        while True:
            remaining = max(0, int(deadline - self.monotonic.monotonic() + 0.999))
            if remaining == 0:
                return True
            live.update(
                self.display.create_text(
                    f"Retrying in {remaining} seconds. Press r to rotate or q to quit.",
                    style="yellow",
                )
            )
            readable, _, _ = select.select([sys.stdin], [], [], min(1.0, remaining))
            if not readable:
                continue
            action = sys.stdin.read(1).lower()
            if action == "q":
                return False
            if action == "r" and self._rotate_retry_credentials(console, spotify):
                return True

    def _rotate_retry_credentials(self, console: Console, spotify: Spotify) -> bool:
        """Rotate retry credentials.

        Args:
            console: Rich console receiving this command's output.
            spotify: Spotify supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        rotate = getattr(spotify, "rotate_credentials", None)
        if not callable(rotate):
            console.print(
                (
                    "This Spotify client cannot rotate credentials; c"
                    "ontinuing the retry wait."
                ),
                style="bold yellow",
            )
            return False
        try:
            label = rotate()
        except Exception as exc:
            console.print(
                f"Could not rotate credentials: {exc} Continuing the retry wait.",
                style="bold yellow",
            )
            return False
        console.print(f"Rotated to {label}; retrying now.", style="bold green")
        return True
