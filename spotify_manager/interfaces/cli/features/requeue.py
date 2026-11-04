"""Explicit requeue CLI execution, prompts and presentation."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from dataclasses import field
from typing import Never

import typer
from rich.status import Status
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.runtime import Wait
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.output import StatusOutput
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.cli.terminal import TerminalPrompt
from spotify_manager.interfaces.operations import (
    requeue_for_a_dream as requeue_for_a_dream,
)
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class RequeueCLI:
    """Run Requeue progression and present its outcome.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        display: Terminal rendering and operator prompt constructors.
        sleep: Bounded retry wait supplied by the interface.
    """

    runtime: CliResources

    display: ConsoleDisplay
    sleep: Wait
    _status: Status | None = field(default=None, init=False, repr=False)

    async def _run_flush_requeue_for_a_dream(self, dry_run: bool) -> None:
        """Advance the first Requeue for a Dream artist by one release.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._flush_requeue_for_a_dream_console = self.display.create_console()
        configuration = await self.runtime.configuration()
        try:
            playlist_id = requeue_for_a_dream.parse_playlist_id(
                configuration.reqeueue_for_a_dream_playlist
            )
        except requeue_for_a_dream.RequeueForADreamConfigError as exc:
            self._report_flush_requeue_for_a_dream_configuration_failure(exc)
        try:
            summary = await self._execute(playlist_id, dry_run)
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_flush_requeue_for_a_dream_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_flush_requeue_for_a_dream_server_failure(exc)
        except requeue_for_a_dream.RequeueForADreamError as exc:
            self._report_flush_requeue_for_a_dream_requeue_for_a_dream_failure(exc)
        except SpotifyException as exc:
            self._report_flush_requeue_for_a_dream_spotify_spotify_failure(exc)
        self._show_flush_requeue_for_a_dream(dry_run, summary)

    async def _execute(
        self, playlist_id: str, dry_run: bool
    ) -> requeue_for_a_dream.RequeueForADreamSummary:
        with self._flush_requeue_for_a_dream_console.status(
            "Planning Requeue for a Dream" + (" (dry run)" if dry_run else "")
        ) as status:
            self._status = status
            interaction = FlushRequeueForADreamInteraction(self)
            return await requeue_for_a_dream.flush_requeue_for_a_dream(
                await self.runtime.review_client(),
                playlist_id,
                dry_run=dry_run,
                echo=interaction,
                progress_callback=StatusOutput(status),
                retry_call=interaction,
                album_reader=interaction,
            )

    async def _prompt_album(
        self,
        source: requeue_for_a_dream.PlaylistTrack,
        release: requeue_for_a_dream.DiscographyRelease,
    ) -> str:
        if self._status is not None:
            self._status.stop()
        try:
            return await self._read_album(source, release)
        finally:
            if self._status is not None:
                self._status.start()

    async def _read_album(
        self,
        source: requeue_for_a_dream.PlaylistTrack,
        release: requeue_for_a_dream.DiscographyRelease,
    ) -> str:
        console = self._flush_requeue_for_a_dream_console
        console.print(
            f"Next album for {source.primary_artist_name}: {release.name} "
            f"({release.release_type}, {release.chronology_date}, "
            f"{release.total_tracks} tracks).",
            markup=False,
        )
        console.print(f"Current: {source.release.name} · {source.name}", markup=False)
        console.print(f"https://open.spotify.com/album/{release.spotify_id}")
        console.print(
            "Skipping every remaining album completes the artist and removes "
            "the current marker (preview only in dry run)."
        )
        answer = await TerminalPrompt(self.display.prompt).ask(
            "Accept album (a) / skip album (s) / cancel (c)",
            choices=["a", "s", "c"],
            default="c",
            console=console,
        )
        return {"a": "accept", "s": "skip", "c": "cancel"}[answer]

    def _flush_requeue_for_a_dream_echo(self, line: str = "") -> None:
        style = "bold green" if line.startswith(("Added", "Removed")) else "cyan"
        self._flush_requeue_for_a_dream_console.print(line, style=style, markup=False)

    def _report_flush_requeue_for_a_dream_configuration_failure(
        self, exc: requeue_for_a_dream.RequeueForADreamConfigError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_requeue_for_a_dream_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            (
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_requeue_for_a_dream_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_flush_requeue_for_a_dream_requeue_for_a_dream_failure(
        self, exc: requeue_for_a_dream.RequeueForADreamError
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            str(exc), style="bold red", markup=False
        )
        raise typer.Exit(code=1) from exc

    def _report_flush_requeue_for_a_dream_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._flush_requeue_for_a_dream_console.print(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _show_flush_requeue_for_a_dream(
        self, dry_run: bool, summary: requeue_for_a_dream.RequeueForADreamSummary
    ) -> None:
        """Show flush requeue for a dream.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
            summary: Completed routine outcome to render.
        """
        table = self.display.create_table(title="Requeue for a Dream")
        table.add_column("Artist")
        table.add_column("Current release")
        table.add_column("Action")
        table.add_column("Next release")
        table.add_column("First track")
        action = {
            "advance": "would advance" if dry_run else "advanced",
            "drop": "would drop" if dry_run else "dropped",
            "empty": "empty",
            "skip": "skipped",
            "cancel": "cancelled",
        }[summary.action]
        if summary.target_already_present:
            action += " (already present)"
        if summary.reason:
            action += f" ({summary.reason})"
        table.add_row(
            summary.artist or ("-"),
            summary.source_release or ("-"),
            action,
            summary.target_release or ("-"),
            summary.target_track or ("-"),
        )
        self._flush_requeue_for_a_dream_console.print(table)
        self._flush_requeue_for_a_dream_console.print(
            (
                f"Playlist: {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after} tracks"
            )
            + (" (preview only)." if dry_run else "."),
            style="bold cyan" if dry_run else "bold green",
        )


@dataclass(frozen=True)
class FlushRequeueForADreamInteraction:
    """Own the original terminal interaction resources.

    Args:
        owner: Command instance owning its console, progress and wait state.
    """

    owner: RequeueCLI

    async def choose_album(
        self,
        source: requeue_for_a_dream.PlaylistTrack,
        release: requeue_for_a_dream.DiscographyRelease,
    ) -> str:
        """Ask the operator to accept, skip or cancel this successor proposal.

        Args:
            source: Unchanged current playlist marker.
            release: Proposed successor album or EP.

        Returns:
            Explicit operator decision, with cancellation as the empty-input default.
        """
        return await self.owner._prompt_album(source, release)

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return SpotifyRetries(self, self.owner.sleep, 10, 3).attempts(description)

    def echo(self, message: str) -> None:
        """Present the command's original message.

        Args:
            message: Complete original text.
        """
        self.owner._flush_requeue_for_a_dream_echo(message)
