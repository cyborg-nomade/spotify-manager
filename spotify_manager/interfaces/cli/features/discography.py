"""Explicit discography CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.interfaces.operations import discography as discography
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import something_old as something_old
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class DiscographyCLI:
    """Execute and present discography through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        prompt: Rich prompt implementation supplied by the facade.
        configuration: Original settings factory supplied by the facade.
        create_table: Factory for table instances.
        _print_discography_plan:  print discography plan supplied by the caller.
        ask_discography_release_selection: Original ask discography release selection
            boundary supplied by the facade.
        ask_something_old_artist: Original ask something old artist boundary supplied by
            the facade.
        review_client: Original Spotify client factory supplied by the facade.
        sleep: Original retry delay boundary supplied by the facade.
    """

    create_console: type[Console]
    prompt: type[Prompt]
    configuration: type[Settings]
    create_table: type[Table]
    _print_discography_plan: Callable[..., None]
    ask_discography_release_selection: Callable[..., tuple[str, ...]]
    ask_something_old_artist: Callable[..., str]
    review_client: Callable[..., Spotify]
    sleep: Callable[[float], None]

    def _prompt_discography_release_selection(
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
            return self._read_discography_release_selection(
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
        table = self.create_table(title="Next discographies")
        table.add_column("Queue")
        table.add_column("Artist")
        table.add_column("Releases", justify="right")
        table.add_column("Days", justify="right")
        for selection in plan.artists:
            table.add_row(
                discography.QUEUE_LABELS[selection.source_queue],
                selection.name,
                str(selection.release_count),
                (f"{selection.days:g}"),
            )
        console.print(table)
        if not plan.artists:
            console.print(
                "No artists with selected releases were found.", style="yellow"
            )
            return
        summary = (
            "Total: "
            f"{plan.total_releases}"
            " releases over "
            f"{plan.days:g}"
            " days. Next queue: "
            f"{discography.QUEUE_LABELS[plan.next_queue]}"
            "."
        )
        console.print(summary, style="bold cyan")
        if plan.open_slots:
            console.print(
                (
                    "No remaining artist fit the final "
                    f"{plan.open_slots}"
                    " release slots; they remain open."
                ),
                style="yellow",
            )

    def _run_plan_discographies(self, dry_run: bool) -> None:
        """Choose the next round-week discographies and clear their queue markers.

        Args:
            dry_run: Whether to preview changes using the original routine behavior.
        """
        self._plan_discographies_console = self.create_console()
        configuration = self.configuration()
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
            summary = self._plan_and_apply(playlist_ids, queue_3_playlist_id, dry_run)
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
        except KeyboardInterrupt as exc:
            self._report_plan_discographies_interrupted_interrupted(exc)
        if summary is None:
            return
        self._show_plan_discographies(summary)

    def _plan_discographies_echo(self, line: str = "") -> None:
        self._plan_discographies_console.print(line, style="cyan", markup=False)

    def _plan_discographies_retry_call(
        self, operation: Callable[[], object], description: str
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self._plan_discographies_echo,
            sleep=self.sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _plan_discographies_ask_discography_release_selection(
        self,
        artist: discography.QueueArtist,
        candidates: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        return self.ask_discography_release_selection(
            self._plan_discographies_console,
            artist,
            candidates,
            self._plan_discographies_status_ref,
        )

    def _plan_discographies_ask_something_old_artist(
        self,
        artist_name: str,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        return self.ask_something_old_artist(
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
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
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
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"),
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    def _report_plan_discographies_interrupted_interrupted(
        self, exc: KeyboardInterrupt
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
                "Removed "
                f"{summary.removed_artists}"
                " artists ("
                f"{summary.removed_markers}"
                " marker tracks). The next run starts with "
                f"{discography.QUEUE_LABELS[summary.next_queue]}"
                "."
            ),
            style="bold green",
        )

    def _read_discography_release_selection(
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
        table = self.create_table(title=f"Choose releases for {artist.name}")
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
            response = self.prompt.ask(
                "Release numbers/ranges to include / [n]one / [q]uit",
                default=default,
                console=console,
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

    def _plan_and_apply(
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
            plan = discography.build_discography_plan(
                self.review_client(),
                playlist_ids,
                self._plan_discographies_ask_discography_release_selection,
                queue_3_playlist_id=queue_3_playlist_id,
                historical_artist_choice_reader=self._plan_discographies_ask_something_old_artist,
                retry_call=self._plan_discographies_retry_call,
                progress_callback=self._plan_discographies_status.update,
            )
        self._print_discography_plan(self._plan_discographies_console, plan)
        if not self._confirm_plan(plan, dry_run):
            return None
        with self._plan_discographies_console.status(
            "Removing confirmed discography artists"
        ) as self._plan_discographies_status:
            return discography.apply_discography_plan(
                self.review_client(),
                plan,
                retry_call=self._plan_discographies_retry_call,
                progress_callback=self._plan_discographies_status.update,
            )

    def _confirm_plan(self, plan: discography.DiscographyPlan, dry_run: bool) -> bool:
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
        action = self.prompt.ask(
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
