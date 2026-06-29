"""FastAPI interface exposing the same logic as the Typer CLI.

Run with::

    uvicorn spotify_manager.api:app --reload

or via the installed script ``spotify-api``.

The two lookups are files-first (source of truth: ``YourLibrary.json``).
``artist-stats`` is fully local; ``album-evaluation`` makes a single live call
to fetch the album's track list. The long-running command endpoints execute
synchronously. The parsed library is cached; call ``POST /library/refresh``
after re-exporting YourLibrary.json.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from spotipy import Spotify

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile
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


class CommandResult(BaseModel):
    """Result of running a side-effecting command endpoint."""

    command: str
    status: str = "completed"
    detail: str | None = None


class CountResult(BaseModel):
    """Number of artists in the YourLibrary file."""

    count: int


@lru_cache
def get_client() -> Spotify:
    """Provide a cached spotipy client (overridable in tests)."""
    return get_spotipy_client()


@lru_cache
def get_library() -> YourLibraryFile:
    """Provide the parsed YourLibrary.json, cached for the process."""
    return load_your_library_file()


ClientDep = Annotated[Spotify, Depends(get_client)]
LibraryDep = Annotated[YourLibraryFile, Depends(get_library)]


app = FastAPI(title="Spotify Manager", version="0.1.0")


@app.exception_handler(ArtistNotFoundError)
def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AlbumNotFoundError)
def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousAlbumError)
def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/library/refresh", response_model=CommandResult)
def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json."""
    get_library.cache_clear()
    return CommandResult(command="library_refresh")


# --------------------------------------------------------------------------- #
# Lookups (files-first)
# --------------------------------------------------------------------------- #
@app.get("/artists/stats", response_model=ArtistLibraryStats)
def artist_stats(
    library: LibraryDep,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Liked-track and saved-release counts for an artist (local files only)."""
    if not name and not artist_id:
        raise HTTPException(status_code=400, detail="provide name or artist_id")
    return get_artist_library_stats(name=name, artist_id=artist_id, library=library)


@app.get("/albums/evaluation", response_model=AlbumEvaluation)
def album_evaluation(
    client: ClientDep,
    library: LibraryDep,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Keep/remove decision for an album (album id resolved locally)."""
    if not name and not album_id:
        raise HTTPException(status_code=400, detail="provide name or album_id")
    return evaluate_album(
        client,
        name=name,
        album_id=album_id,
        artist=artist,
        library=library,
        threshold=threshold,
    )


# --------------------------------------------------------------------------- #
# Mirrored CLI commands
# --------------------------------------------------------------------------- #
@app.post("/commands/monthly-routines", response_model=CommandResult)
def cmd_monthly_routines(client: ClientDep) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly)."""
    compare_your_library_and_all_albums()
    convert_your_library_file(client)
    run_monthly_routines(client)
    return CommandResult(command="monthly_routines")


@app.post("/commands/update-total-albums", response_model=CommandResult)
def cmd_update_total_albums(
    client: ClientDep, just_update: bool = False
) -> CommandResult:
    """Update the total album list."""
    albums = update_total_album_list(client, just_update)
    return CommandResult(
        command="update_total_albums", detail=f"{len(albums)} albums in list"
    )


@app.post("/commands/restore-your-library", response_model=CommandResult)
def cmd_restore_your_library(client: ClientDep) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file."""
    restore_your_library_from_file(client)
    return CommandResult(command="restore_your_library")


@app.post("/commands/compare-lib-files", response_model=CommandResult)
def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file."""
    compare_your_library_and_all_albums()
    return CommandResult(command="compare_lib_files")


@app.post("/commands/analyse-comp", response_model=CommandResult)
def cmd_analyse_comp(client: ClientDep) -> CommandResult:
    """Analyse the saved comparison file against the live library."""
    analyse_comparison(client)
    return CommandResult(command="analyse_comp")


@app.post("/commands/convert-lib", response_model=CommandResult)
def cmd_convert_lib(client: ClientDep) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file."""
    convert_your_library_file(client)
    return CommandResult(command="convert_lib")


@app.get("/commands/count-artists", response_model=CountResult)
def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file."""
    return CountResult(count=count_artists_in_library())


@app.post("/commands/analyse-library", response_model=CommandResult)
def cmd_analyse_library() -> CommandResult:
    """Analyse the library and save stats."""
    analyse_library_routine()
    return CommandResult(command="analyse_library")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (entry point for the ``spotify-api`` script)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
