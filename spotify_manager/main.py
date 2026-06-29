"""Interface file."""

import typer
from spotipy import Spotify

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.processors.library_lookups import get_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
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


def client() -> Spotify:
    """Build the Spotify client lazily, so files-only commands never touch it."""
    global _client
    if _client is None:
        _client = get_spotipy_client()
    return _client


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
) -> None:
    """Decide whether an album should be kept (>= threshold liked) or removed."""
    if not name and not album_id:
        raise typer.BadParameter("provide an album NAME or --album-id")
    try:
        evaluation = evaluate_album(
            client(),
            name=name,
            album_id=album_id,
            artist=artist,
            threshold=threshold,
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


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
