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
from spotify_manager.routines import review_album_limits
from spotify_manager.routines.analyse_library import analyse_library_routine
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
    """."""
    analyse_library_routine()


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
        elif " keep: " in line:
            style = "green"
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
                client(),
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


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
