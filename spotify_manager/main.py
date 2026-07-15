"""Interface file."""

import typer
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table
from spotipy import Spotify

# UFI
from spotify_manager.client import SpotifyRedirectURIError
from spotify_manager.client import get_spotipy_client
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.processors.library_lookups import get_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_sync
from spotify_manager.routines import recover_removed_albums
from spotify_manager.routines import review_album_limits
from spotify_manager.routines.convert_library_file import analyse_comparison
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import convert_your_library_file
from spotify_manager.routines.convert_library_file import restore_your_library_from_file
from spotify_manager.routines.count_items import count_artists_in_library
from spotify_manager.routines.monthly_routine import run_monthly_routines


app = typer.Typer()

_client: Spotify | None = None
_review_client: Spotify | None = None
DISABLED_SPOTIFY_STATUS_FORCELIST = (999,)
REVIEW_ACTION_CHOICES = [
    "r",
    "remove",
    "k",
    "keep",
    "s",
    "skip",
    "d",
    "details",
    "q",
    "quit",
]


def client() -> Spotify:
    """Build the Spotify client lazily, so files-only commands never touch it."""
    global _client
    if _client is None:
        try:
            _client = get_spotipy_client()
        except SpotifyRedirectURIError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    return _client


def review_client() -> Spotify:
    """Build a no-retry client for interactive review operations."""
    global _review_client
    if _review_client is None:
        try:
            _review_client = get_spotipy_client(
                retries=0,
                status_retries=0,
                status_forcelist=DISABLED_SPOTIFY_STATUS_FORCELIST,
            )
        except SpotifyRedirectURIError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    return _review_client


def ask_review_action(
    console: Console,
    evaluation: object,
    progress: Progress | None = None,
) -> str:
    """Ask for a review action while yielding Rich progress rendering."""
    default = "r"
    if getattr(evaluation, "decision", None) != "remove":
        default = "s"

    if progress is not None:
        progress.stop()
    try:
        return Prompt.ask(
            "Action [r]emove / [k]eep anyway / [s]kip / [d]etails / [q]uit",
            choices=REVIEW_ACTION_CHOICES,
            default=default,
            console=console,
        )
    finally:
        if progress is not None:
            progress.start()


@app.command()
def monthly_routines() -> None:
    """Run monthly routines."""
    compare_your_library_and_all_albums()
    convert_your_library_file(client())
    run_monthly_routines(client())


@app.command()
def update_total_albums(just_update: bool = False) -> None:
    """Update total album list, optional flag to just add the remaining pages."""
    update_total_album_list(client(), just_update)


@app.command()
def restore_your_library() -> None:
    """."""
    restore_your_library_from_file(client())


@app.command()
def compare_lib_files() -> None:
    """."""
    compare_your_library_and_all_albums()


@app.command()
def analyse_comp() -> None:
    """."""
    analyse_comparison(client())


@app.command()
def convert_lib() -> None:
    """."""
    convert_your_library_file(client())


@app.command()
def count_artists() -> None:
    """Print the number of artists in the YourLibrary file."""
    print(count_artists_in_library())


@app.command()
def analyse_library() -> None:
    """Synchronize local library mirrors from live Spotify data."""
    console = Console()
    labels = {
        "albums": "Saved albums",
        "tracks": "Liked tracks",
        "artists": "Followed artists",
    }
    source_labels = {
        "live_api": "Live API",
        "export_fallback": "Export fallback",
        "verified_fallback": "Merged + live verified",
        "seeded_live_verified": "Seeded + live verified",
        "seeded_live_verified_no_discovery": "Seeded + verified (no discovery)",
        "merged_track_fallback": "Merged fallback",
    }

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            tasks = {
                resource: progress.add_task(label, total=None)
                for resource, label in labels.items()
            }

            def update_progress(
                resource: str,
                completed: int,
                total: int | None,
                status: str,
            ) -> None:
                progress.update(
                    tasks[resource],
                    completed=completed,
                    total=total,
                    description=f"{labels[resource]}: {status}",
                )

            summary = library_sync.analyse_library_routine(
                review_client(),
                echo=lambda line: console.print(line, style="yellow", markup=False),
                progress_callback=update_progress,
            )
    except library_sync.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "Library sync progress was saved; rerun the same command to resume.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except library_sync.SpotifyTransientServerError as exc:
        console.print(
            "Spotify API temporarily unavailable "
            f"({exc.http_status}) after {exc.attempts} attempts "
            f"while {exc.operation}.",
            style="bold yellow",
        )
        console.print(
            "Library sync progress was saved; rerun the same command to resume.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except library_sync.LibrarySyncError as exc:
        console.print(str(exc), style="bold red")
        console.print(
            "No partial staging data was published. Rerun to resume after fixing "
            "the underlying issue.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc

    table = Table(title="Library mirror updated")
    table.add_column("Resource")
    table.add_column("Source")
    table.add_column("Previous", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Added", justify="right", style="green")
    table.add_column("Removed", justify="right", style="red")
    table.add_column("Skipped", justify="right", style="yellow")
    for resource in summary.resources:
        table.add_row(
            labels[resource.resource],
            source_labels.get(resource.source, resource.source),
            str(resource.previous),
            str(resource.current),
            str(resource.added),
            str(resource.removed),
            str(resource.skipped),
        )
    console.print(table)
    console.print(f"Run: {summary.run_id}", style="bold")
    console.print(f"Undo backup: {summary.backup_dir}", style="dim")
    console.print(
        f"Audit manifest: {summary.backup_dir}/manifest.json",
        style="dim",
    )


@app.command(name="restore-library-sync")
def restore_library_sync_command(
    run_id: str = typer.Argument(help="Completed library-sync run id."),
    yes: bool = typer.Option(False, "--yes", help="Restore without prompting."),
) -> None:
    """Restore generated library files from a sync backup."""
    if not yes and not typer.confirm(
        f"Restore generated library files from sync {run_id}?"
    ):
        raise typer.Abort()
    try:
        restored = library_sync.restore_library_sync(run_id)
    except library_sync.LibrarySyncRestoreError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Restored: {', '.join(restored)}")


@app.command()
def artist_stats(
    name: str = typer.Argument(None, help="Artist name (as in your export)."),
    artist_id: str = typer.Option(None, "--artist-id", help="Spotify artist id."),
) -> None:
    """Show liked-track and saved-release counts for an artist (local files)."""
    if not name and not artist_id:
        raise typer.BadParameter("provide an artist NAME or --artist-id")
    try:
        stats = get_artist_library_stats(name=name, artist_id=artist_id)
    except ArtistNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(stats.model_dump_json(indent=2))


@app.command()
def album_decision(
    name: str = typer.Argument(None, help="Album name (as in your export)."),
    album_id: str = typer.Option(None, "--album-id", help="Spotify album id."),
    artist: str = typer.Option(None, "--artist", help="Disambiguate by artist."),
    threshold: float = 0.5,
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore the local tracklist cache for this run."
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", help="Re-fetch the tracklist and update the cache."
    ),
) -> None:
    """Decide whether an album should be kept (>= threshold liked) or removed."""
    if not name and not album_id:
        raise typer.BadParameter("provide an album NAME or --album-id")
    try:
        evaluation = evaluate_album(
            client_factory=client,
            name=name,
            album_id=album_id,
            artist=artist,
            threshold=threshold,
            use_cache=not no_cache,
            refresh_cache=refresh_cache,
        )
    except AmbiguousAlbumError as exc:
        typer.echo(str(exc), err=True)
        for candidate in exc.candidates:
            typer.echo(
                f"  {candidate['artist']} - {candidate['album']} ({candidate['id']})",
                err=True,
            )
        raise typer.Exit(code=1) from exc
    except AlbumNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(evaluation.model_dump_json(indent=2))


@app.command(name="review-album-limits")
def review_album_limits_command(
    threshold: float = 0.5,
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignore the local tracklist cache for this run."
    ),
    refresh_cache: bool = typer.Option(
        False, "--refresh-cache", help="Re-fetch tracklists and update the cache."
    ),
) -> None:
    """Interactively remove saved albums below the liked-track threshold."""
    if threshold < 0 or threshold > 1:
        raise typer.BadParameter("threshold must be between 0 and 1")

    console = Console()
    progress_ref: Progress | None = None

    def echo(line: str = "") -> None:
        style = None
        if line.startswith("Followed artist") or line.startswith("Recorded artist"):
            style = "cyan"
        elif line.startswith("Updated stats_history"):
            style = "cyan dim"
        elif " keep: " in line or "previously kept" in line:
            style = "green"
        elif line.startswith("Kept anyway:"):
            style = "bold green"
        elif "remove candidate" in line:
            style = "yellow"
        elif line.startswith("Removed:") or line.startswith("Auto-removed"):
            style = "bold red"
        elif line.startswith("Live liked tracks"):
            style = "cyan"
        elif line.startswith("Skipped:"):
            style = "dim yellow"
        elif line.startswith("Review complete"):
            style = "bold"

        console.print(line, style=style, markup=False)

    def read_action(
        _album: object,
        evaluation: object,
    ) -> str:
        return ask_review_action(console, evaluation, progress_ref)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            progress_ref = progress
            task_id = progress.add_task("Reviewing albums", total=None)

            def update_progress(position: int, total: int) -> None:
                progress.update(task_id, completed=position, total=total)

            review_album_limits.review_album_limits(
                review_client(),
                action_reader=read_action,
                threshold=threshold,
                use_cache=not no_cache,
                refresh_cache=refresh_cache,
                echo=echo,
                progress_callback=update_progress,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "Progress was saved up to the last successful removal.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            "Spotify API temporarily unavailable "
            f"({exc.http_status}) after {exc.attempts} attempts "
            f"while {exc.operation}.",
            style="bold yellow",
        )
        console.print(
            "Progress was saved up to the last successful removal.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc


@app.command(name="recover-removed-albums")
def recover_removed_albums_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report changes without following artists or restoring albums.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Process at most this many pending albums.",
    ),
) -> None:
    """Audit removed albums, follow credited artists, and restore future releases."""
    console = Console()

    def echo(line: str = "") -> None:
        style = None
        if line.startswith("Followed credited artist"):
            style = "cyan"
        elif line.startswith("Would follow") or line.startswith("Would restore"):
            style = "yellow"
        elif line.startswith("Multiple credited artists"):
            style = "magenta"
        elif line.startswith("Restored future release"):
            style = "bold green"
        elif line.startswith("Future release already saved"):
            style = "green"
        elif line.startswith("Album unavailable"):
            style = "yellow"
        elif line.startswith("Recovery complete") or line.startswith(
            "Dry run complete"
        ):
            style = "bold"
        console.print(line, style=style, markup=False)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            description = "Auditing removed albums"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(position: int, total: int) -> None:
                progress.update(task_id, completed=position, total=total)

            recover_removed_albums.recover_removed_albums(
                review_client(),
                echo=echo,
                progress_callback=update_progress,
                dry_run=dry_run,
                limit=limit,
            )
    except recover_removed_albums.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "Recovery progress was saved up to the last completed album.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except recover_removed_albums.SpotifyTransientServerError as exc:
        console.print(
            "Spotify API temporarily unavailable "
            f"({exc.http_status}) after {exc.attempts} attempts "
            f"while {exc.operation}.",
            style="bold yellow",
        )
        console.print(
            "Recovery progress was saved up to the last completed album.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
