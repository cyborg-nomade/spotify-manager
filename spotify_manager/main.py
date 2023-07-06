"""Interface file."""

import typer

# UFI
from spotify_manager.routines.monthly_routine import run_monthly_routines
from spotify_manager.processors.total_albums_processor import update_total_album_list

app = typer.Typer()


@app.command()
def monthly_routines():
    """Run monthly routines."""
    run_monthly_routines()


@app.command()
def update_total_albums(just_update: bool = False):
    """Update total album list, optional flag to just add the remaining pages."""
    update_total_album_list(just_update)


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
