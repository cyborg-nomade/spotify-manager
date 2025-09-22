"""Interface file."""

import typer

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines.convert_library_file import analyse_comparison
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import convert_your_library_file
from spotify_manager.routines.convert_library_file import restore_your_library_from_file
from spotify_manager.routines.count_items import count_artists_in_library
from spotify_manager.routines.monthly_routine import run_monthly_routines


app = typer.Typer()
sp = get_spotipy_client()


@app.command()
def monthly_routines():
    """Run monthly routines."""
    run_monthly_routines(sp)


@app.command()
def update_total_albums(just_update: bool = False):
    """Update total album list, optional flag to just add the remaining pages."""
    update_total_album_list(sp, just_update)


@app.command()
def restore_your_library():
    """."""
    restore_your_library_from_file(sp)


@app.command()
def compare_lib_files():
    """."""
    compare_your_library_and_all_albums()


@app.command()
def analyse_comp():
    """."""
    analyse_comparison(sp)


@app.command()
def convert_lib():
    """."""
    convert_your_library_file(sp)


@app.command()
def count_artists():
    """."""
    count_artists_in_library()


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
