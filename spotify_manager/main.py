"""Interface file."""

import json as json
import select as select
import sys as sys
import termios as termios
import tty as tty
from collections.abc import Callable as Callable
from collections.abc import Iterable as Iterable
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from pathlib import Path as Path
from time import monotonic as monotonic
from time import sleep as sleep
from typing import Annotated as Annotated

import typer as typer
from requests.exceptions import RequestException as RequestException
from rich.console import Console as Console
from rich.live import Live as Live
from rich.progress import BarColumn as BarColumn
from rich.progress import MofNCompleteColumn as MofNCompleteColumn
from rich.progress import Progress as Progress
from rich.progress import SpinnerColumn as SpinnerColumn
from rich.progress import TextColumn as TextColumn
from rich.progress import TimeElapsedColumn as TimeElapsedColumn
from rich.prompt import Prompt as Prompt
from rich.status import Status as Status
from rich.table import Table as Table
from rich.text import Text as Text
from spotipy import Spotify as Spotify
from spotipy.exceptions import SpotifyException as SpotifyException

from spotify_manager.bootstrap.startup import (
    hydrate_library_data as hydrate_runtime_library_data,
)
from spotify_manager.client import RotatingSpotify as RotatingSpotify
from spotify_manager.client import (
    SpotifyClientConfigurationError as SpotifyClientConfigurationError,
)
from spotify_manager.client import SpotifyRedirectURIError as SpotifyRedirectURIError
from spotify_manager.client import get_spotipy_client as get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient as LastFmClient
from spotify_manager.client.lastfm import LastFmError as LastFmError
from spotify_manager.core.library_data import ALL_ARTIFACTS as ALL_ARTIFACTS
from spotify_manager.core.library_data import ArtifactName as ArtifactName
from spotify_manager.core.library_data import LibraryDataError as LibraryDataError
from spotify_manager.core.library_data.models import (
    validate_artifact_name as validate_artifact_name,
)
from spotify_manager.core.library_data.runtime import (
    get_library_data_service as get_library_data_service,
)
from spotify_manager.core.state.models import StateDocumentError as StateDocumentError
from spotify_manager.core.state.models import StateError as StateError
from spotify_manager.core.state.runtime import get_state_service as get_state_service
from spotify_manager.interfaces.cli.features.album_review import (
    AlbumReviewCLI as AlbumReviewCLI,
)
from spotify_manager.interfaces.cli.features.analysis import AnalysisCLI as AnalysisCLI
from spotify_manager.interfaces.cli.features.artist_review import (
    ArtistReviewCLI as ArtistReviewCLI,
)
from spotify_manager.interfaces.cli.features.discography import (
    DiscographyCLI as DiscographyCLI,
)
from spotify_manager.interfaces.cli.features.discovery import (
    DiscoveryCLI as DiscoveryCLI,
)
from spotify_manager.interfaces.cli.features.found_art import FoundArtCLI as FoundArtCLI
from spotify_manager.interfaces.cli.features.genre import GenreCLI as GenreCLI
from spotify_manager.interfaces.cli.features.historical import (
    HistoricalCLI as HistoricalCLI,
)
from spotify_manager.interfaces.cli.features.library_commands import (
    LibraryCommandsCLI as LibraryCommandsCLI,
)
from spotify_manager.interfaces.cli.features.library_data import (
    LibraryDataCLI as LibraryDataCLI,
)
from spotify_manager.interfaces.cli.features.library_upload import (
    LibraryUploadCLI as LibraryUploadCLI,
)
from spotify_manager.interfaces.cli.features.lookups import LookupsCLI as LookupsCLI
from spotify_manager.interfaces.cli.features.new_year import NewYearCLI as NewYearCLI
from spotify_manager.interfaces.cli.features.palace import PalaceCLI as PalaceCLI
from spotify_manager.interfaces.cli.features.queue import QueueCLI as QueueCLI
from spotify_manager.interfaces.cli.features.queue_3 import Queue3CLI as Queue3CLI
from spotify_manager.interfaces.cli.features.recovery import RecoveryCLI as RecoveryCLI
from spotify_manager.interfaces.cli.features.releases import ReleasesCLI as ReleasesCLI
from spotify_manager.interfaces.cli.features.requeue import RequeueCLI as RequeueCLI
from spotify_manager.interfaces.cli.features.sauvignon import (
    SauvignonCLI as SauvignonCLI,
)
from spotify_manager.interfaces.cli.features.slow_listening import (
    SlowListeningCLI as SlowListeningCLI,
)
from spotify_manager.interfaces.cli.features.something_old import (
    SomethingOldCLI as SomethingOldCLI,
)
from spotify_manager.interfaces.cli.features.spotify_auth import SpotifyAuthCLI
from spotify_manager.interfaces.cli.features.state import StateCLI as StateCLI
from spotify_manager.interfaces.cli.features.wine import WineCLI as WineCLI
from spotify_manager.interfaces.cli.history import HistoryCommand as HistoryCommand
from spotify_manager.interfaces.cli.history import (
    present_history_summary as present_history_summary,
)
from spotify_manager.processors.library_lookups import (
    AlbumNotFoundError as AlbumNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousAlbumError as AmbiguousAlbumError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousArtistError as AmbiguousArtistError,
)
from spotify_manager.processors.library_lookups import (
    ArtistNotFoundError as ArtistNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    SpotifyLookupResponseError as SpotifyLookupResponseError,
)
from spotify_manager.processors.library_lookups import (
    evaluate_album_live as evaluate_album_live,
)
from spotify_manager.processors.library_lookups import (
    get_live_artist_library_stats as get_live_artist_library_stats,
)
from spotify_manager.processors.total_albums_processor import (
    update_total_album_list as update_total_album_list,
)
from spotify_manager.routines import analyse_library as library_sync
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines import blast_from_past_artists as blast_from_past_artists
from spotify_manager.routines import composer_playlists as composer_playlists
from spotify_manager.routines import daily_mind_radio as daily_mind_radio
from spotify_manager.routines import discography as discography
from spotify_manager.routines import found_art as found_art
from spotify_manager.routines import genre_reveal as genre_reveal
from spotify_manager.routines import new_kids as new_kids
from spotify_manager.routines import new_wine as new_wine
from spotify_manager.routines import new_year as new_year
from spotify_manager.routines import palace_of_memory as palace_of_memory
from spotify_manager.routines import queue_3 as queue_3
from spotify_manager.routines import recover_removed_albums as recover_removed_albums
from spotify_manager.routines import release_check as release_check
from spotify_manager.routines import requeue_for_a_dream as requeue_for_a_dream
from spotify_manager.routines import review_album_limits as review_album_limits
from spotify_manager.routines import review_artists as artist_review
from spotify_manager.routines import sauvignon as sauvignon
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines import slow_listening as slow_listening
from spotify_manager.routines import something_old as something_old
from spotify_manager.routines import the_queue as the_queue
from spotify_manager.routines import upload_library_files as hf_upload
from spotify_manager.routines.convert_library_file import (
    analyse_comparison as analyse_comparison,
)
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums as compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import (
    convert_your_library_file as convert_your_library_file,
)
from spotify_manager.routines.convert_library_file import (
    restore_your_library_from_file as restore_your_library_from_file,
)
from spotify_manager.routines.count_items import (
    count_artists_in_library as count_artists_in_library,
)
from spotify_manager.routines.monthly_routine import (
    run_monthly_routines as run_monthly_routines,
)
from spotify_manager.settings import Settings as Settings


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


def _library_data_cli() -> LibraryDataCLI:
    return LibraryDataCLI(
        create_console=Console,
        create_table=Table,
        format_file_size=format_file_size,
        get_library_data_service=get_library_data_service,
        selected_artifacts=selected_artifacts,
        validate_artifact_name=validate_artifact_name,
    )


def _album_review_cli() -> AlbumReviewCLI:
    return AlbumReviewCLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        REVIEW_ACTION_CHOICES=REVIEW_ACTION_CHOICES,
        spinner_column=SpinnerColumn,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_review_action=ask_review_action,
        review_client=review_client,
    )


def _artist_review_cli() -> ArtistReviewCLI:
    return ArtistReviewCLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_artist_release_choice=ask_artist_release_choice,
        ask_artist_track_choice=ask_artist_track_choice,
        review_client=review_client,
    )


def _wine_cli() -> WineCLI:
    return WineCLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_new_wine_endpoint_choice=ask_new_wine_endpoint_choice,
        ask_new_wine_release_choice=ask_new_wine_release_choice,
        review_client=review_client,
        sleep=sleep,
    )


def _discovery_cli() -> DiscoveryCLI:
    return DiscoveryCLI(
        bar_column=BarColumn,
        create_console=Console,
        create_lastfm=LastFmClient,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_new_kids_release_choice=ask_new_kids_release_choice,
        print_album_discovery_decisions=print_album_discovery_decisions,
        review_client=review_client,
        sleep=sleep,
    )


def _slow_listening_cli() -> SlowListeningCLI:
    return SlowListeningCLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        acknowledge_slow_listening_completion=acknowledge_slow_listening_completion,
        ask_slow_listening_action=ask_slow_listening_action,
        ask_slow_listening_release_order=ask_slow_listening_release_order,
        review_client=review_client,
        sleep=sleep,
    )


def _queue_3_cli() -> Queue3CLI:
    return Queue3CLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        _render_queue_3_annual_import=_render_queue_3_annual_import,
        ask_queue_3_composer_playlist=ask_queue_3_composer_playlist,
        ask_queue_3_release_transition=ask_queue_3_release_transition,
        review_client=review_client,
        sleep=sleep,
    )


def _discography_cli() -> DiscographyCLI:
    return DiscographyCLI(
        create_console=Console,
        prompt=Prompt,
        configuration=Settings,
        create_table=Table,
        _print_discography_plan=_print_discography_plan,
        ask_discography_release_selection=ask_discography_release_selection,
        ask_something_old_artist=ask_something_old_artist,
        review_client=review_client,
        sleep=sleep,
    )


def _library_commands_cli() -> LibraryCommandsCLI:
    return LibraryCommandsCLI(
        analyse_comparison=analyse_comparison,
        client=client,
        compare_your_library_and_all_albums=compare_your_library_and_all_albums,
        convert_your_library_file=convert_your_library_file,
        count_artists_in_library=count_artists_in_library,
        restore_your_library_from_file=restore_your_library_from_file,
        run_monthly_routines=run_monthly_routines,
        update_total_album_list=update_total_album_list,
    )


def _state_cli() -> StateCLI:
    return StateCLI(create_console=Console, get_state_service=get_state_service)


def _library_upload_cli() -> LibraryUploadCLI:
    return LibraryUploadCLI(
        create_console=Console, create_table=Table, format_file_size=format_file_size
    )


def _found_art_cli() -> FoundArtCLI:
    return FoundArtCLI(
        create_console=Console,
        create_lastfm=LastFmClient,
        configuration=Settings,
        create_table=Table,
        create_text=Text,
        client=client,
        print_found_art_table=print_found_art_table,
    )


def _sauvignon_cli() -> SauvignonCLI:
    return SauvignonCLI(
        bar_column=BarColumn,
        create_console=Console,
        create_lastfm=LastFmClient,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_sauvignon_album=ask_sauvignon_album,
        print_sauvignon_table=print_sauvignon_table,
        review_client=review_client,
        sleep=sleep,
    )


def _queue_cli() -> QueueCLI:
    return QueueCLI(
        bar_column=BarColumn,
        create_console=Console,
        create_lastfm=LastFmClient,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_queue_artist=ask_queue_artist,
        configured_queue_playlists=configured_queue_playlists,
        print_queue_fill_table=print_queue_fill_table,
        print_queue_flush_table=print_queue_flush_table,
        review_client=review_client,
        sleep=sleep,
    )


def _historical_cli() -> HistoricalCLI:
    return HistoricalCLI(
        create_console=Console,
        configuration=Settings,
        create_table=Table,
        client=client,
        print_scrobble_selection_table=print_scrobble_selection_table,
        review_client=review_client,
        sleep=sleep,
        create_text=Text,
    )


def _something_old_cli() -> SomethingOldCLI:
    return SomethingOldCLI(
        create_console=Console,
        create_lastfm=LastFmClient,
        prompt=Prompt,
        configuration=Settings,
        create_table=Table,
        _scrobble_date=_scrobble_date,
        ask_something_old_album=ask_something_old_album,
        ask_something_old_artist=ask_something_old_artist,
        ask_something_old_mode=ask_something_old_mode,
        client=client,
        print_scrobble_history_summary=print_scrobble_history_summary,
        print_something_old_summary=print_something_old_summary,
    )


def _releases_cli() -> ReleasesCLI:
    return ReleasesCLI(
        bar_column=BarColumn,
        create_console=Console,
        create_lastfm=LastFmClient,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        prompt=Prompt,
        configuration=Settings,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        ask_release_check_artist=ask_release_check_artist,
        ask_release_check_release=ask_release_check_release,
        client=client,
        print_release_check_summary=print_release_check_summary,
        print_scrobble_history_summary=print_scrobble_history_summary,
    )


def _new_year_cli() -> NewYearCLI:
    return NewYearCLI(
        create_console=Console,
        create_lastfm=LastFmClient,
        configuration=Settings,
        client=client,
    )


def _requeue_cli() -> RequeueCLI:
    return RequeueCLI(
        create_console=Console,
        configuration=Settings,
        create_table=Table,
        review_client=review_client,
        sleep=sleep,
    )


def _palace_cli() -> PalaceCLI:
    return PalaceCLI(
        create_console=Console,
        configuration=Settings,
        create_table=Table,
        create_text=Text,
        review_client=review_client,
        sleep=sleep,
    )


def _genre_cli() -> GenreCLI:
    return GenreCLI(
        create_console=Console,
        configuration=Settings,
        create_table=Table,
        client=client,
    )


def _analysis_cli() -> AnalysisCLI:
    return AnalysisCLI(
        bar_column=BarColumn,
        create_console=Console,
        create_live=Live,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        spinner_column=SpinnerColumn,
        create_table=Table,
        create_text=Text,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        monotonic=monotonic,
        print_library_analysis_summary=print_library_analysis_summary,
        review_client=review_client,
        run_library_analysis=run_library_analysis,
        sleep=sleep,
        wait_for_library_retry=wait_for_library_retry,
    )


def _lookups_cli() -> LookupsCLI:
    return LookupsCLI(
        client=client,
        evaluate_album_live=evaluate_album_live,
        get_live_artist_library_stats=get_live_artist_library_stats,
    )


def _recovery_cli() -> RecoveryCLI:
    return RecoveryCLI(
        bar_column=BarColumn,
        create_console=Console,
        complete_column=MofNCompleteColumn,
        create_progress=Progress,
        spinner_column=SpinnerColumn,
        text_column=TextColumn,
        time_column=TimeElapsedColumn,
        review_client=review_client,
    )


@app.callback()
def initialize_shared_library_data(ctx: typer.Context) -> None:
    """Hydrate durable canonical files before ordinary CLI commands."""
    if ctx.invoked_subcommand in {
        "library-data-status",
        "library-data-pull",
        "library-data-push",
    }:
        return
    hydrate_runtime_library_data()


def selected_artifacts(values: Iterable[str]) -> tuple[ArtifactName, ...]:
    """Validate repeated artifact options, defaulting to every artifact."""
    return _library_data_cli()._selected_artifacts(values)


def client() -> Spotify:
    """Build the Spotify client lazily, so files-only commands never touch it."""
    global _client
    if _client is None:
        try:
            _client = get_spotipy_client(event_callback=typer.echo)
        except (SpotifyRedirectURIError, SpotifyClientConfigurationError) as exc:
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
                event_callback=typer.echo,
            )
        except (SpotifyRedirectURIError, SpotifyClientConfigurationError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    return _review_client


def ask_review_action(
    console: Console, evaluation: object, progress: Progress | None = None
) -> str:
    """Ask for a review action while yielding Rich progress rendering."""
    return _album_review_cli()._prompt_review_action(console, evaluation, progress)


def ask_artist_track_choice(
    console: Console,
    artist: object,
    candidates: tuple[artist_review.TrackCandidate, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for one ambiguous ranked track."""
    return _artist_review_cli()._prompt_artist_track_choice(
        console, artist, candidates, progress
    )


def ask_artist_release_choice(
    console: Console,
    artist: object,
    candidates: tuple[artist_review.ReleaseCandidate, ...],
    allow_decline: bool,
    progress: Progress | None = None,
) -> str:
    """Prompt for one eligible release, with an optional permanent decline."""
    return _artist_review_cli()._prompt_artist_release_choice(
        console, artist, candidates, allow_decline, progress
    )


def ask_new_wine_release_choice(
    console: Console,
    source: new_wine.PlaylistTrack,
    candidates: tuple[new_wine.ReleaseCandidate, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for the release that should follow the current release."""
    return _wine_cli()._prompt_new_wine_release_choice(
        console, source, candidates, progress
    )


def ask_new_wine_endpoint_choice(
    console: Console,
    source: new_wine.PlaylistTrack,
    tracks: tuple[new_wine.ReleaseTrack, ...],
    current_index: int,
    progress: Progress | None = None,
) -> str:
    """Ask whether the current track is the release's canonical endpoint."""
    return _wine_cli()._prompt_new_wine_endpoint_choice(
        console, source, tracks, current_index, progress
    )


def ask_new_kids_release_choice(
    console: Console,
    artist_name: str,
    candidates: tuple[new_kids.ChoiceCandidate, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for the next release or matching composer works playlist."""
    return _discovery_cli()._prompt_new_kids_release_choice(
        console, artist_name, candidates, progress
    )


def print_album_discovery_decisions(
    console: Console, title: str, decisions: tuple[new_kids.FlushResult, ...]
) -> None:
    """Render shared New Kids and Queue 2 artist decisions."""
    return _discovery_cli()._render_album_discovery_decisions(console, title, decisions)


def ask_slow_listening_release_order(
    console: Console,
    release_date: str,
    candidates: tuple[slow_listening.DiscographyRelease, ...],
    progress: Progress | None = None,
) -> tuple[str, ...]:
    """Prompt for chronological order when Spotify dates are identical."""
    return _slow_listening_cli()._prompt_slow_listening_release_order(
        console, release_date, candidates, progress
    )


def ask_slow_listening_action(
    console: Console,
    source: new_wine.PlaylistTrack,
    target: new_wine.ReleaseTrack,
    target_release: slow_listening.DiscographyRelease,
    progress: Progress | None = None,
) -> str:
    """Ask whether the proposed replacement should be added or skipped."""
    return _slow_listening_cli()._prompt_slow_listening_action(
        console, source, target, target_release, progress
    )


def ask_queue_3_release_transition(
    console: Console,
    source: new_wine.PlaylistTrack,
    current_release: slow_listening.DiscographyRelease,
    next_release: slow_listening.DiscographyRelease,
    progress: Progress | None = None,
) -> str:
    """Confirm the next chronological release at a Queue 3 boundary."""
    return _queue_3_cli()._prompt_queue_3_release_transition(
        console, source, current_release, next_release, progress
    )


def ask_queue_3_composer_playlist(
    console: Console,
    artist_name: str,
    candidates: tuple[queue_3.OwnedPlaylist, ...],
    progress: Progress | None = None,
) -> str:
    """Choose one owned composer playlist when names are ambiguous."""
    return _queue_3_cli()._prompt_queue_3_composer_playlist(
        console, artist_name, candidates, progress
    )


def ask_discography_release_selection(
    console: Console,
    artist: discography.QueueArtist,
    candidates: tuple[discography.CatalogRelease, ...],
    status: Status | None = None,
) -> tuple[str, ...]:
    """Prompt for the exact canonical releases to count for one artist."""
    return _discography_cli()._prompt_discography_release_selection(
        console, artist, candidates, status
    )


def acknowledge_slow_listening_completion(
    console: Console, source: new_wine.PlaylistTrack, progress: Progress | None = None
) -> None:
    """Pause after an artist leaves Slow Listening so its slot can be filled."""
    return _slow_listening_cli()._acknowledge_slow_listening_completion(
        console, source, progress
    )


@app.command()
def monthly_routines() -> None:
    """Run monthly routines."""
    return _library_commands_cli()._monthly_routines()


@app.command()
def update_total_albums(just_update: bool = False) -> None:
    """Update total album list, optional flag to just add the remaining pages."""
    return _library_commands_cli()._update_total_albums(just_update)


@app.command()
def restore_your_library() -> None:
    """."""
    return _library_commands_cli()._restore_your_library()


@app.command()
def compare_lib_files() -> None:
    """."""
    return _library_commands_cli()._compare_lib_files()


@app.command()
def analyse_comp() -> None:
    """."""
    return _library_commands_cli()._analyse_comp()


@app.command()
def convert_lib() -> None:
    """."""
    return _library_commands_cli()._convert_lib()


@app.command()
def count_artists() -> None:
    """Print the number of artists in the YourLibrary file."""
    return _library_commands_cli()._count_artists()


@app.command(name="state-show")
def state_show_command(
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        "-n",
        help="Show one namespace value instead of the complete state.",
    ),
) -> None:
    """Print the current shared state and its guarded revision."""
    return _state_cli()._run_state_show(namespace)


@app.command(name="state-export")
def state_export_command(
    destination: Annotated[Path, typer.Argument(help="Destination JSON file.")] = Path(
        "spotify-manager-state.json"
    ),
) -> None:
    """Export a readable snapshot of the complete shared state."""
    return _state_cli()._run_state_export(destination)


@app.command(name="state-edit")
def state_edit_command(
    source: Annotated[
        Path, typer.Argument(help="Edited JSON state snapshot to apply.")
    ],
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow an older exported snapshot to replace the current state.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Apply without the confirmation prompt."
    ),
) -> None:
    """Validate and apply an edited shared-state snapshot safely."""
    return _state_cli()._run_state_edit(source, force, yes)


def format_file_size(size_bytes: int) -> str:
    """Format a byte count for a compact CLI summary."""
    return _library_data_cli()._format_file_size(size_bytes)


@app.command(name="library-data-status")
def library_data_status_command() -> None:
    """Show durable versions and local synchronization for canonical files."""
    return _library_data_cli()._run_library_data_status()


@app.command(name="library-data-pull")
def library_data_pull_command(
    artifact: Annotated[
        list[str] | None,
        typer.Option(
            "--artifact",
            "-a",
            help="Pull albums, tracks, artists, or scrobbles; repeat as needed.",
        ),
    ] = None,
) -> None:
    """Hydrate canonical working files from the shared dataset."""
    return _library_data_cli()._run_library_data_pull(artifact)


@app.command(name="library-data-push")
def library_data_push_command(
    artifact: Annotated[
        list[str] | None,
        typer.Option(
            "--artifact",
            "-a",
            help="Push albums, tracks, artists, or scrobbles; repeat as needed.",
        ),
    ] = None,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Publish without confirmation."
    ),
) -> None:
    """Publish canonical working files to the shared dataset."""
    return _library_data_cli()._run_library_data_push(artifact, yes)


@app.command(name="upload-library-files-to-hf")
def upload_library_files_to_hf_command(
    your_library_only: bool = typer.Option(
        False,
        "--your-library-only",
        help="Upload YourLibrary.json without the Last.fm export.",
    ),
    lastfm_only: bool = typer.Option(
        False,
        "--lastfm-only",
        help="Upload the Last.fm export without YourLibrary.json.",
    ),
    repo_id: str = typer.Option(
        hf_upload.DEFAULT_REPO_ID,
        "--repo-id",
        help="Hugging Face Space repository id.",
    ),
    revision: str = typer.Option(
        hf_upload.DEFAULT_REVISION,
        "--revision",
        help="Hugging Face Space branch or revision.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and summarize without changing local files or HF.",
    ),
) -> None:
    """Upload refreshed Spotify and Last.fm exports to the HF Space."""
    return _library_upload_cli()._run_upload_library_files_to_hf(
        your_library_only, lastfm_only, repo_id, revision, dry_run
    )


def print_scrobble_selection_table(
    console: Console,
    title: str,
    results: tuple[blast_from_past.SpotifySelectionResult, ...],
) -> None:
    """Print Last.fm selections and their Spotify outcomes."""
    return _historical_cli()._render_scrobble_selection_table(console, title, results)


def print_found_art_table(
    console: Console, results: tuple[found_art.FoundArtResult, ...]
) -> None:
    """Print ranked Last.fm candidates and their Spotify outcomes."""
    return _found_art_cli()._render_found_art_table(console, results)


def print_sauvignon_table(
    console: Console, results: tuple[sauvignon.SauvignonResult, ...]
) -> None:
    """Render album-level Last.fm recommendations for Sauvignon."""
    return _sauvignon_cli()._render_sauvignon_table(console, results)


def print_queue_fill_table(
    console: Console, results: tuple[the_queue.FillResult, ...]
) -> None:
    """Render Last.fm artist recommendations resolved for The Queue."""
    return _queue_cli()._render_queue_fill_table(console, results)


def print_queue_flush_table(
    console: Console, results: tuple[the_queue.FlushResult, ...]
) -> None:
    """Render Queue top-track transitions and live-like decisions."""
    return _queue_cli()._render_queue_flush_table(console, results)


def print_scrobble_history_summary(
    console: Console, summary: scrobble_history.ScrobbleHistorySummary
) -> None:
    """Render one compact Last.fm history refresh summary.

    Args:
        console: Original command-owned terminal console.
        summary: Accepted history outcome to present without changing its values.
    """
    present_history_summary(console, summary)


def _scrobble_date(timestamp_ms: int) -> str:
    """Format one Last.fm timestamp in the listening timezone."""
    return _historical_cli()._scrobble_date(timestamp_ms)


def ask_something_old_artist(
    console: Console,
    artist_name: str,
    candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    status: Status,
) -> str:
    """Prompt when Spotify has several exact-name artist matches."""
    return _something_old_cli()._prompt_something_old_artist(
        console, artist_name, candidates, status
    )


def ask_release_check_artist(
    console: Console,
    artist: release_check.RankedArtist,
    candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    progress: Progress,
) -> str:
    """Prompt for one ambiguous Last.fm-to-Spotify artist mapping."""
    return _releases_cli()._prompt_release_check_artist(
        console, artist, candidates, progress
    )


def ask_queue_artist(
    console: Console,
    recommendation: the_queue.ArtistRecommendation,
    candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    progress: Progress,
) -> str:
    """Prompt for an ambiguous Last.fm Queue artist mapping."""
    return _queue_cli()._prompt_queue_artist(
        console, recommendation, candidates, progress
    )


def ask_sauvignon_album(
    console: Console,
    recommendation: sauvignon.AlbumRecommendation,
    options: tuple[sauvignon.SpotifyAlbumOption, ...],
    progress: Progress,
) -> str:
    """Prompt only when Spotify exposes materially different album editions."""
    return _sauvignon_cli()._prompt_sauvignon_album(
        console, recommendation, options, progress
    )


def ask_release_check_release(
    console: Console,
    artist: release_check.RankedArtist,
    release: release_check.ReleaseCandidate,
    track: release_check.ReleaseTrack,
    destinations: tuple[str, ...],
    unattached_single: bool,
    progress: Progress,
) -> str:
    """Prompt immediately before adding one eligible release."""
    return _releases_cli()._prompt_release_check_release(
        console, artist, release, track, destinations, unattached_single, progress
    )


def print_release_check_summary(
    console: Console, summary: release_check.ReleaseCheckSummary
) -> None:
    """Render the release window and every discovered release decision."""
    return _releases_cli()._render_release_check_summary(console, summary)


def ask_something_old_mode(
    console: Console,
    artist: something_old.GoldenOldieArtist,
    spotify_artist: something_old.SpotifyArtistCandidate,
    status: Status,
) -> str:
    """Prompt for Last.fm tracks, Spotify tracks, or one album/EP."""
    return _something_old_cli()._prompt_something_old_mode(
        console, artist, spotify_artist, status
    )


def ask_something_old_album(
    console: Console,
    artist: something_old.GoldenOldieArtist,
    releases: tuple[slow_listening.DiscographyRelease, ...],
    status: Status,
) -> str:
    """Prompt for one chronologically displayed studio album or EP."""
    return _something_old_cli()._prompt_something_old_album(
        console, artist, releases, status
    )


def print_something_old_summary(
    console: Console, summary: something_old.SomethingOldSummary
) -> None:
    """Render Golden Oldies context and the selected Spotify tracks."""
    return _something_old_cli()._render_something_old_summary(console, summary)


@app.command(name="new-year")
def new_year_command(
    year: int | None = typer.Option(
        None, help="Completed source year; defaults to last year."
    ),
    dry_run: bool = typer.Option(True, "--dry-run/--apply"),
) -> None:
    """Build the annual retrospective, or preview it without changing Spotify."""
    return _new_year_cli()._run_new_year(year, dry_run)


@app.command(name="update-scrobble-history")
def update_scrobble_history_command(
    full_rebuild: bool = typer.Option(
        False,
        "--full-rebuild",
        help="Replace all history from the API, including past edits and deletions.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Fetch and report new scrobbles without changing local files.",
    ),
) -> None:
    """Update the canonical Last.fm export used by every history routine."""
    HistoryCommand(
        console=Console(),
        configuration=Settings(),
        validate=found_art.validate_lastfm_configuration,
        create_client=LastFmClient,
        refresh=scrobble_history.refresh_scrobble_history,
        present=print_scrobble_history_summary,
    ).run(full_rebuild, dry_run)


@app.command(name="something-old")
def something_old_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve and display the selection without changing files or Spotify.",
    ),
) -> None:
    """Fill an empty Something Old slot from Last.fm Golden Oldies."""
    return _something_old_cli()._run_something_old(dry_run)


@app.command(name="check-new-releases")
def check_new_releases_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Show release decisions without changing "
            "playlists; Last.fm history and artist mapping "
            "choices are still persisted."
        ),
    ),
) -> None:
    """Check Last.fm's most-played artists for newly released music."""
    return _releases_cli()._run_check_new_releases(dry_run)


@app.command(name="found-art")
def found_art_command(
    count: int | None = typer.Option(
        None,
        "--count",
        min=1,
        help="Number of unheard tracks to add (default: 20).",
    ),
    max_playlist_length: int | None = typer.Option(
        None,
        "--max-playlist-length",
        min=1,
        help="Fill up to this playlist length instead of using --count.",
    ),
    seed_count: int = typer.Option(
        found_art.DEFAULT_SEED_COUNT,
        "--seed-count",
        min=1,
        help="Number of listening-history seeds sent to Last.fm.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Rank and resolve recommendations without changing Spotify.",
    ),
) -> None:
    """Build Last.fm-style unheard recommendations for Found Art."""
    return _found_art_cli()._run_found_art(
        count, max_playlist_length, seed_count, dry_run
    )


@app.command(name="fill-sauvignon-from-lastfm")
def fill_sauvignon_from_lastfm_command(
    count: int | None = typer.Option(
        None, "--count", min=1, help="Number of unheard albums to add."
    ),
    max_playlist_length: int | None = typer.Option(
        None,
        "--max-playlist-length",
        min=1,
        help="Fill to this Sauvignon length instead of using --count.",
    ),
    seed_count: int = typer.Option(
        sauvignon.DEFAULT_SEED_COUNT,
        "--seed-count",
        min=1,
        help="Number of listening-history tracks sent to Last.fm.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve album recommendations without changing Spotify.",
    ),
) -> None:
    """Recommend unheard albums from Last.fm and add them to Sauvignon."""
    return _sauvignon_cli()._run_fill_sauvignon_from_lastfm(
        count, max_playlist_length, seed_count, dry_run
    )


def configured_queue_playlists(configuration: Settings) -> the_queue.QueuePlaylists:
    """Parse every playlist used by The Queue's fill and flush commands."""
    return _queue_cli()._configured_queue_playlists(configuration)


@app.command(name="fill-queue-from-lastfm")
def fill_queue_from_lastfm_command(
    count: int | None = typer.Option(
        None,
        "--count",
        min=1,
        help="Number of unheard artists to add (default: 20).",
    ),
    max_playlist_length: int | None = typer.Option(
        None,
        "--max-playlist-length",
        min=1,
        help="Fill to this Queue length instead of using --count.",
    ),
    seed_count: int = typer.Option(
        the_queue.DEFAULT_SEED_COUNT,
        "--seed-count",
        min=1,
        help="Number of listening-history artists sent to Last.fm.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Resolve recommendations without changing Spotify."
    ),
) -> None:
    """Recommend unheard artists from Last.fm and add them to The Queue."""
    return _queue_cli()._run_fill_queue_from_lastfm(
        count, max_playlist_length, seed_count, dry_run
    )


@app.command(name="flush-queue")
def flush_queue_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Plan the first ten Queue artists without changing Spotify or state.",
    ),
) -> None:
    """Advance the first ten Queue artists through Spotify's top tracks."""
    return _queue_cli()._run_flush_queue(dry_run)


@app.command(name="flush-new-kids")
def flush_new_kids_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the complete run without changing Spotify or durable state.",
    ),
) -> None:
    """Advance New Kids artists and refill the playlist from Queue 2."""
    return _discovery_cli()._run_flush_new_kids(dry_run)


@app.command(name="flush-queue-2")
def flush_queue_2_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the Queue 2 run without changing Spotify or durable state.",
    ),
) -> None:
    """Fill New Kids, then advance the first ten Queue 2 artists."""
    return _discovery_cli()._run_flush_queue_2(dry_run)


@app.command(name="flush-new-wine")
def flush_new_wine_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the complete flush plan without changing Spotify or state.",
    ),
    no_discovery: bool = typer.Option(
        False,
        "--no-discovery",
        help="Refill only from artists with 18 liked tracks or 3 saved albums.",
    ),
    choose_album_endpoints: bool = typer.Option(
        False,
        "--choose-album-endpoints",
        help="Ask whether each current Album/EP track is its canonical endpoint.",
    ),
) -> None:
    """Advance every New Wine track once according to its release."""
    return _wine_cli()._run_flush_new_wine(
        dry_run, no_discovery, choose_album_endpoints
    )


def _render_queue_3_annual_import(
    console: Console, results: tuple[queue_3.AnnualImportResult, ...]
) -> None:
    """Render previous-year Queue 3 markers consistently across commands."""
    return _queue_3_cli()._show_annual_import(console, results)


@app.command(name="import-queue-3-previous-year")
def import_queue_3_previous_year_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview last year's Great Discoveries import without changing Queue 3.",
    ),
) -> None:
    """Import last year's Great Discoveries without advancing Queue 3."""
    return _queue_3_cli()._run_import_queue_3_previous_year(dry_run)


@app.command(name="flush-queue-3")
def flush_queue_3_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Preview the annual import and next ten artist "
            "transitions without changing Spotify or state."
        ),
    ),
) -> None:
    """Advance the first ten Queue 3 artists through studio discographies."""
    return _queue_3_cli()._run_flush_queue_3(dry_run)


@app.command(name="flush-slow-listening")
def flush_slow_listening_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the next two transitions without changing Spotify or state.",
    ),
) -> None:
    """Advance the first two Slow Listening tracks through studio releases."""
    return _slow_listening_cli()._run_flush_slow_listening(dry_run)


@app.command(name="flush-requeue-for-a-dream")
def flush_requeue_for_a_dream_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the next release transition without changing Spotify.",
    ),
) -> None:
    """Advance the first Requeue for a Dream artist by one release."""
    return _requeue_cli()._run_flush_requeue_for_a_dream(dry_run)


def _print_discography_plan(
    console: Console, plan: discography.DiscographyPlan
) -> None:
    """Render one compact discography listening plan."""
    return _discography_cli()._render_discography_plan(console, plan)


@app.command(name="plan-discographies")
def plan_discographies_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build the interactive plan without removing playlist markers.",
    ),
) -> None:
    """Choose the next round-week discographies and clear their queue markers."""
    return _discography_cli()._run_plan_discographies(dry_run)


@app.command(name="fill-palace-of-memory")
def fill_palace_of_memory_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve the ten albums without changing Spotify or the cursor.",
    ),
    alphabetical_start: str | None = typer.Option(
        None,
        "--alphabetical-start",
        help=(
            "Start the alphabetical selection at this "
            "1-based position, Spotify album id/URI/URL, "
            "exact album title, or 'Artist - Album'."
        ),
    ),
    set_alphabetical_cursor: int | None = typer.Option(
        None,
        "--set-alphabetical-cursor",
        min=1,
        help=(
            "Persist this 1-based position as the next "
            "alphabetical album and exit without changing "
            "the playlist."
        ),
    ),
) -> None:
    """Add five alphabetical and five historical album first tracks."""
    return _palace_cli()._run_fill_palace_of_memory(
        dry_run, alphabetical_start, set_alphabetical_cursor
    )


@app.command(name="blast-from-the-past")
def blast_from_the_past_command(
    count: int | None = typer.Option(
        None,
        "--count",
        min=1,
        help="Number of unique scrobbled dates to process (default: 10).",
    ),
    max_playlist_length: int | None = typer.Option(
        None,
        "--max-playlist-length",
        min=1,
        help="Fill up to this playlist length instead of using --count.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve selections without changing the Spotify playlist.",
    ),
) -> None:
    """Select past scrobbles and add their Spotify matches to the playlist."""
    return _historical_cli()._run_blast_from_the_past(
        count, max_playlist_length, dry_run
    )


@app.command(name="blast-from-the-past-artists")
def blast_from_the_past_artists_command(
    count: int = typer.Option(
        blast_from_past_artists.DEFAULT_COUNT,
        "--count",
        min=1,
        help="Number of alphabetically eligible artists to add (default: 5).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve artists and tracks without changing the playlist.",
    ),
) -> None:
    """Add liked tracks from artists heard recently, but not this year."""
    return _historical_cli()._run_blast_from_the_past_artists(count, dry_run)


@app.command(name="daily-mind-radio")
def daily_mind_radio_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve anniversary tracks without changing the Spotify playlist.",
    ),
) -> None:
    """Add tracks from today's Last.fm anniversaries to Daily Mind Radio."""
    return _historical_cli()._run_daily_mind_radio(dry_run)


@app.command(name="genre-reveal")
def genre_reveal_command(
    state_path: Annotated[
        Path,
        typer.Option(
            "--state-path", help="Path to the shared Genre Reveal progress file."
        ),
    ] = genre_reveal.DEFAULT_STATE_PATH,
    log_path: Annotated[
        Path,
        typer.Option(
            "--log-path", help="Path to the append-only Genre Reveal audit log."
        ),
    ] = genre_reveal.DEFAULT_LOG_PATH,
    open_pages: bool = typer.Option(
        True,
        "--open-pages/--no-open-pages",
        help="Open the Every Noise and Spotify source pages after completion.",
    ),
) -> None:
    """Save and sample the first unchecked Every Noise genre playlist."""
    return _genre_cli()._run_genre_reveal(state_path, log_path, open_pages)


@app.command(name="refresh-spotify-tokens")
def refresh_spotify_tokens() -> None:
    """Authenticate or force-refresh every configured Spotify app token."""
    return _spotify_auth_cli()._refresh_spotify_tokens()


def wait_for_library_retry(
    console: Console,
    notice: library_sync.RetryNotice,
    spotify: Spotify,
    progress: Progress | None = None,
) -> bool:
    """Wait for a retry while accepting rotate or quit without Enter."""
    return _analysis_cli()._wait_for_library_retry(console, notice, spotify, progress)


def print_library_analysis_summary(
    console: Console, summary: library_sync.LibrarySyncSummary
) -> None:
    """Render the common completion table for either analysis mode."""
    return _analysis_cli()._render_library_analysis_summary(console, summary)


def run_library_analysis(mode: library_sync.AnalysisMode) -> None:
    """Run one analysis mode with shared Rich progress and error handling."""
    return _analysis_cli()._run_library_analysis(mode)


@app.command(name="analyse-library-async")
def analyse_library_async() -> None:
    """Build suffixed mirrors exclusively from YourLibrary.json."""
    return _analysis_cli()._analyse_library_async()


@app.command(name="analyse-library-sync")
def analyse_library_sync() -> None:
    """Build suffixed mirrors exclusively from the live Spotify API."""
    return _analysis_cli()._analyse_library_sync()


@app.command(name="restore-library-sync")
def restore_library_sync_command(
    run_id: str = typer.Argument(help="Completed library-analysis run id."),
    yes: bool = typer.Option(False, "--yes", help="Restore without prompting."),
) -> None:
    """Restore generated library files from an async or sync backup."""
    return _analysis_cli()._run_restore_library_sync(run_id, yes)


@app.command()
def artist_stats(
    name: str = typer.Argument(None, help="Exact Spotify artist name."),
    artist_id: str = typer.Option(None, "--artist-id", help="Spotify artist id."),
) -> None:
    """Show live liked-track and saved-release counts for an artist."""
    return _lookups_cli()._artist_stats(name, artist_id)


@app.command()
def album_decision(
    name: str = typer.Argument(None, help="Exact Spotify album name."),
    album_id: str = typer.Option(None, "--album-id", help="Spotify album id."),
    artist: str = typer.Option(None, "--artist", help="Disambiguate by artist."),
    threshold: float = 0.5,
) -> None:
    """Evaluate an album against live Spotify Liked Songs state."""
    return _lookups_cli()._album_decision(name, album_id, artist, threshold)


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
    return _album_review_cli()._run_review_album_limits(
        threshold, no_cache, refresh_cache
    )


@app.command(name="recover-removed-albums")
def recover_removed_albums_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report changes without following artists or restoring albums.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Process at most this many pending albums."
    ),
) -> None:
    """Audit removed albums, follow credited artists, and restore future releases."""
    return _recovery_cli()._run_recover_removed_albums(dry_run, limit)


@app.command(name="review-artists")
def review_artists_command(
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Discard cached catalog candidates before reviewing.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Process at most this many pending artists."
    ),
) -> None:
    """Review followed artists and place one track in the matching queue."""
    return _artist_review_cli()._run_review_artists(refresh_cache, limit)


def _spotify_auth_cli() -> SpotifyAuthCLI:
    return SpotifyAuthCLI(
        review_client=review_client, rotating_client_type=RotatingSpotify
    )


if __name__ == "__main__":
    "Main."
    app()
    print("Done!")
