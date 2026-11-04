"""Present unfiltered track candidates through the interruptible terminal edge."""

from dataclasses import dataclass

from rich.console import Console
from rich.status import Status

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.terminal import TerminalPrompt


@dataclass(frozen=True)
class CliTrackMatching:
    """Suspend progress while the operator selects or rejects a Spotify result.

    Args:
        display: Invocation-owned terminal constructors and prompt.
        console: Active command console.
        status: Progress display to suspend while prompting.
    """

    display: ConsoleDisplay
    console: Console
    status: Status

    def _show(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> None:
        self.console.print(
            f"Choose a Spotify match: {scrobble.artist} - {scrobble.track} - "
            f"{scrobble.album or '(no album)'}",
            markup=False,
        )
        for number, candidate in enumerate(candidates, start=1):
            text = (
                f"{number}. {candidate.track}\n"
                f"   {', '.join(candidate.artists)}\n"
                f"   {candidate.album or '(no album)'}\n"
                f"   https://open.spotify.com/track/{candidate.spotify_id}"
            )
            self.console.print(self.display.create_text(text), soft_wrap=True)
        if not candidates:
            self.console.print("Spotify returned no usable track results.")

    async def choose(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> str:
        """Ask for a numbered result, no match, or cancellation without a default.

        Args:
            scrobble: Original historical play.
            candidates: Unfiltered search results in Spotify order.

        Returns:
            Selected track ID, or an empty string for no match.

        Raises:
            BlastFromPastCancelledError: The operator cancels the invocation.
        """
        self.status.stop()
        try:
            self._show(scrobble, candidates)
            choices = [str(index) for index in range(1, len(candidates) + 1)]
            answer = await TerminalPrompt(self.display.prompt).ask(
                "Select a result / [n]o match / [q]uit",
                choices=choices + ["n", "q"],
                console=self.console,
            )
            if answer == "q":
                raise BlastFromPastCancelledError(
                    "Manual track matching was cancelled."
                )
            return "" if answer == "n" else candidates[int(answer) - 1].spotify_id
        finally:
            self.status.start()
