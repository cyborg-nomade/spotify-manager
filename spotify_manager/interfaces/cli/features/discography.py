"""Explicit discography CLI execution, prompts and presentation."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.status import Status
from rich.table import Table
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.discography_review import ReleaseReviewDraft
from spotify_manager.application.ports.discography_review import ReleaseReviewSubmission
from spotify_manager.application.ports.runtime import Wait
from spotify_manager.domain.discography_links import split_album_references
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.infrastructure.cli_cancellation import CliInterruptedError
from spotify_manager.infrastructure.cli_cancellation import check_cli_interruption
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.features.something_old import SomethingOldCLI
from spotify_manager.interfaces.cli.output import StatusOutput
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.cli.terminal import TerminalPrompt
from spotify_manager.interfaces.operations import discography as discography
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import something_old as something_old


@dataclass(kw_only=True)
class DiscographyCLI:
    """Plan discographies and present release choices in the terminal.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        display: Rich console, table and live-status constructors.
        ask_something_old_artist: Operator prompt for historical artist resolution.
        sleep: Bounded retry wait supplied by the interface.
        historical_artists: Named historical artist selection stage.
    """

    runtime: CliResources

    display: ConsoleDisplay
    historical_artists: SomethingOldCLI
    sleep: Wait

    async def _review_discography_draft(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        status = self._plan_discographies_status_ref
        if status is not None:
            status.stop()
        try:
            return await self._read_discography_draft(draft)
        finally:
            if status is not None:
                status.start()

    async def _read_discography_draft(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        self._show_discography_draft(draft)
        indexes = _selected_indexes(draft)
        default = discography.format_release_indexes(indexes)
        while True:
            response = (
                await TerminalPrompt(self.display.prompt).ask(
                    "Release numbers/ranges / [a]dd album links / [n]one / [q]uit",
                    default=default,
                    console=self._plan_discographies_console,
                )
            ).strip()
            if response.casefold() == "q":
                return ReleaseReviewSubmission("quit")
            if response.casefold() == "n":
                return ReleaseReviewSubmission("none")
            if response.casefold() == "a":
                return await self._read_discography_links(draft)
            try:
                indexes = discography.parse_release_indexes(
                    response, len(draft.entries)
                )
            except ValueError:
                self._plan_discographies_console.print(
                    "Enter valid release numbers.", markup=False
                )
                continue
            identities = []
            for index in indexes:
                identities.append(draft.entries[index - 1].release.spotify_id)
            return ReleaseReviewSubmission("select", tuple(identities))

    async def _read_discography_links(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        text = await TerminalPrompt(self.display.prompt).ask(
            "Spotify album links/URIs (separate with spaces or commas)",
            default="",
            console=self._plan_discographies_console,
        )
        return ReleaseReviewSubmission(
            "add", draft.selected_ids, split_album_references(text)
        )

    def _show_discography_draft(self, draft: ReleaseReviewDraft) -> None:
        console = self._plan_discographies_console
        table = self.display.create_table(
            title=f"Review releases for {draft.artist.name}"
        )
        for column in ("#", "Release", "Type / date", "Tracks", "Credits", "Selected"):
            table.add_column(column)
        for index, entry in enumerate(draft.entries, start=1):
            release = entry.release
            table.add_row(
                str(index),
                self.display.create_text(release.name),
                f"{release.release_type} · {release.chronology_date}",
                str(release.total_tracks),
                self.display.create_text(", ".join(entry.artists) or draft.artist.name),
                "yes" if release.spotify_id in draft.selected_ids else "-",
            )
        console.print(table)
        if draft.remaining is not None:
            console.print(
                f"{draft.remaining} release slots remain in this week.", markup=False
            )
        for notice in draft.notices:
            console.print(notice, markup=False)

    async def _prompt_discography_release_selection(
        self,
        console: Console,
        artist: discography.QueueArtist,
        candidates: tuple[discography.CatalogRelease, ...],
        status: Status | None,
    ) -> tuple[str, ...]:
        """Prompt for the exact canonical releases to count for one artist.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            status: Status supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if status is not None:
            status.stop()
        try:
            return await self._read_discography_release_selection(
                console, artist, candidates, status
            )
        finally:
            if status is not None:
                status.start()

    def _render_discography_plan(
        self, console: Console, plan: discography.DiscographyPlan
    ) -> None:
        """Render one compact discography listening plan.

        Args:
            console: Rich console receiving this command's output.
            plan: Plan supplied by the caller.
        """
        table = self.display.create_table(title="Next discographies")
        table.add_column("Queue")
        table.add_column("Artist")
        table.add_column("Releases", justify="right")
        table.add_column("Days", justify="right")
        for selection in plan.artists:
            table.add_row(
                discography.QUEUE_LABELS[selection.source_queue],
                selection.name,
                str(selection.release_count),
                f"{selection.days:g}",
            )
        console.print(table)
        if not plan.artists:
            console.print(
                "No artists with selected releases were found.", style="yellow"
            )
            return
        summary = (
            f"Total: {plan.total_releases} releases over {plan.days:g}"
            f" days. Next queue: {discography.QUEUE_LABELS[plan.next_queue]}."
        )
        console.print(summary, style="bold cyan")
        if plan.open_slots:
            console.print(
                (
                    f"No remaining artist fit the final {plan.open_slots}"
                    f" release slots; they remain open."
                ),
                style="yellow",
            )

    async def _run_plan_discographies(self, dry_run: bool) -> None:
        """Choose the next round-week discographies and clear their queue markers.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._plan_discographies_console = self.display.create_console()
        configuration = await self.runtime.configuration()
        try:
            playlist_ids = discography.parse_playlist_ids(
                configuration.discography_newfoundland_playlist,
                configuration.discography_memory_lane_playlist,
                configuration.discography_requeue_playlist,
            )
            queue_3_playlist_id = discography.parse_playlist_id(
                configuration.the_queue_3_playlist, "THE_QUEUE_3_PLAYLIST"
            )
        except discography.DiscographyConfigError as exc:
            self._report_plan_discographies_configuration_failure(exc)
        self._plan_discographies_status_ref: Status | None = None
        try:
            summary = await self._plan_and_apply(
                playlist_ids, queue_3_playlist_id, dry_run
            )
        except review_album_limits.SpotifyRateLimitError as exc:
            self._report_plan_discographies_rate_limit(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._report_plan_discographies_server_failure(exc)
        except discography.DiscographyCancelledError as exc:
            self._report_plan_discographies_cancelled(exc)
        except discography.DiscographyError as exc:
            self._report_plan_discographies_discography_failure(exc)
        except SpotifyException as exc:
            self._report_plan_discographies_spotify_spotify_failure(exc)
        except (KeyboardInterrupt, CliInterruptedError) as exc:
            self._report_plan_discographies_interrupted_interrupted(exc)
        if summary is None:
            return
        self._show_plan_discographies(summary)

    def _plan_discographies_echo(self, line: str = "") -> None:
        self._plan_discographies_console.print(line, style="cyan", markup=False)

    async def _plan_discographies_ask_discography_release_selection(
        self,
        artist: discography.QueueArtist,
        candidates: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        return await self._prompt_discography_release_selection(
            self._plan_discographies_console,
            artist,
            candidates,
            self._plan_discographies_status_ref,
        )

    async def _plan_discographies_ask_something_old_artist(
        self,
        artist_name: str,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        return await self.historical_artists.ask_artist(
            self._plan_discographies_console,
            artist_name,
            candidates,
            self._plan_discographies_status,
        )

    def _report_plan_discographies_configuration_failure(
        self, exc: discography.DiscographyConfigError
    ) -> Never:
        self._plan_discographies_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_plan_discographies_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError
    ) -> Never:
        self._plan_discographies_console.print(
            (
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
            ),
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_plan_discographies_server_failure(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> Never:
        self._plan_discographies_console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    def _report_plan_discographies_cancelled(
        self, exc: discography.DiscographyCancelledError
    ) -> Never:
        self._plan_discographies_console.print(
            str(exc), style="bold yellow", markup=False
        )
        raise typer.Exit(code=0) from exc

    def _report_plan_discographies_discography_failure(
        self, exc: discography.DiscographyError
    ) -> Never:
        self._plan_discographies_console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_plan_discographies_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        self._plan_discographies_console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_plan_discographies_interrupted_interrupted(
        self, exc: KeyboardInterrupt | CliInterruptedError
    ) -> Never:
        self._plan_discographies_console.print(
            "Discography planning cancelled.", style="bold yellow"
        )
        raise typer.Exit(code=0) from exc

    def _show_plan_discographies(
        self, summary: discography.DiscographyRunSummary
    ) -> None:
        self._plan_discographies_console.print(
            (
                f"Removed {summary.removed_artists} artists ("
                f"{summary.removed_markers}"
                f" marker tracks). The next run starts with "
                f"{discography.QUEUE_LABELS[summary.next_queue]}."
            ),
            style="bold green",
        )

    async def _read_discography_release_selection(
        self,
        console: Console,
        artist: discography.QueueArtist,
        candidates: tuple[discography.CatalogRelease, ...],
        status: Status | None,
    ) -> tuple[str, ...]:
        """Read discography release selection.

        Args:
            console: Rich console receiving this command's output.
            artist: Artist supplied by the caller.
            candidates: Ordered choices offered by the routine.
            status: Status supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        table = self.display.create_table(title=f"Choose releases for {artist.name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Saved")
        table.add_column("Default")
        default_indexes: list[int] = []
        for index, release in enumerate(candidates, start=1):
            self._row_discography_release_selection(
                default_indexes, index, release, table
            )
        console.print(table)
        default = discography.format_release_indexes(tuple(default_indexes))
        while True:
            response = (
                await TerminalPrompt(self.display.prompt).ask(
                    "Release numbers/ranges to include / [n]one / [q]uit",
                    default=default,
                    console=console,
                )
            ).strip()
            if response.casefold() == "q":
                raise discography.DiscographyCancelledError(
                    "Discography planning cancelled during release selection."
                )
            if response.casefold() == "n":
                return ()
            try:
                indexes = discography.parse_release_indexes(response, len(candidates))
            except ValueError:
                console.print(
                    "Enter valid comma-separated numbers or ranges.",
                    style="bold yellow",
                )
                continue
            return tuple(candidates[index - 1].spotify_id for index in indexes)

    def _row_discography_release_selection(
        self,
        default_indexes: list[int],
        index: int,
        release: CatalogRelease,
        table: Table,
    ) -> None:
        if release.default:
            default_indexes.append(index)
        table.add_row(
            str(index),
            release.name,
            release.release_type,
            release.chronology_date,
            str(release.total_tracks),
            "yes" if release.saved else "-",
            "yes" if release.default else "-",
            style=None if release.default else "dim yellow",
        )

    async def _plan_and_apply(
        self,
        playlist_ids: dict[discography.QueueName, str],
        queue_3_playlist_id: str,
        dry_run: bool,
    ) -> discography.DiscographyRunSummary | None:
        """Plan and apply.

        Args:
            playlist_ids: Playlist ids supplied by the caller.
            queue_3_playlist_id: Queue 3 playlist id supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.

        Returns:
            The routine outcome.
        """
        with self._plan_discographies_console.status(
            "Planning the next discography batch"
        ) as self._plan_discographies_status:
            self._plan_discographies_status_ref = self._plan_discographies_status
            plan = await discography.build_discography_plan(
                (await self.runtime.review_client()),
                playlist_ids,
                PlanDiscographiesInteraction(self),
                queue_3_playlist_id=queue_3_playlist_id,
                historical_artist_choice_reader=PlanDiscographiesInteraction(self),
                retry_call=PlanDiscographiesInteraction(self),
                progress_callback=StatusOutput(self._plan_discographies_status),
                review_reader=PlanDiscographiesInteraction(self),
            )
        self._render_discography_plan(self._plan_discographies_console, plan)
        if not (await self._confirm_plan(plan, dry_run)):
            return None
        with self._plan_discographies_console.status(
            "Removing confirmed discography artists"
        ) as self._plan_discographies_status:
            return await discography.apply_discography_plan(
                (await self.runtime.review_client()),
                plan,
                retry_call=PlanDiscographiesInteraction(self),
                progress_callback=StatusOutput(self._plan_discographies_status),
            )

    async def _confirm_plan(
        self, plan: discography.DiscographyPlan, dry_run: bool
    ) -> bool:
        """Confirm plan.

        Args:
            plan: Plan supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.

        Returns:
            The original value selected or formatted by this adapter.
        """
        if not plan.artists or dry_run:
            if dry_run and plan.artists:
                self._plan_discographies_console.print(
                    "Dry run: playlists and queue-priority state were unchanged.",
                    style="bold cyan",
                )
            return False
        action = await TerminalPrompt(self.display.prompt).ask(
            "Remove these artists from the discography queues?",
            choices=["y", "n", "q"],
            default="n",
            console=self._plan_discographies_console,
        )
        if action in {"n", "q"}:
            self._plan_discographies_console.print(
                "Nothing was changed.", style="yellow"
            )
            return False
        return True


@dataclass(frozen=True)
class PlanDiscographiesInteraction:
    """Own the original terminal interaction resources.

    Args:
        owner: Command instance owning its console, progress and wait state.
    """

    owner: DiscographyCLI

    async def review_releases(
        self, draft: ReleaseReviewDraft
    ) -> ReleaseReviewSubmission:
        """Read an editable checklist using the owning terminal command.

        Args:
            draft: Current exact options and addition feedback.

        Returns:
            One edit, selection or cancellation.
        """
        return await self.owner._review_discography_draft(draft)

    def check(self) -> None:
        """Observe terminal interruption at the read-only review boundary.

        Raises:
            CliInterruptedError: The command was interrupted.
        """
        check_cli_interruption()

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
        self.owner._plan_discographies_echo(message)

    async def select_releases(
        self,
        artist: discography.QueueArtist,
        candidates: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        """Use this command's fixed select releases prompt.

        Args:
            artist: Original operator prompt value.
            candidates: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return await self.owner._plan_discographies_ask_discography_release_selection(
            artist, candidates
        )

    async def choose_artist(
        self,
        artist_name: str,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        """Use this command's fixed choose artist prompt.

        Args:
            artist_name: Original operator prompt value.
            candidates: Original operator prompt value.

        Returns:
            Original operator response.
        """
        return await self.owner._plan_discographies_ask_something_old_artist(
            artist_name, candidates
        )


def _selected_indexes(draft: ReleaseReviewDraft) -> tuple[int, ...]:
    selected = []
    for index, entry in enumerate(draft.entries, start=1):
        if entry.release.spotify_id in draft.selected_ids:
            selected.append(index)
    return tuple(selected)
