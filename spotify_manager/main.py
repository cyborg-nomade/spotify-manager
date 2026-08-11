"""Interface file."""

import select
import sys
import termios
import tty
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from time import monotonic
from time import sleep
from typing import Annotated

import typer
from requests.exceptions import RequestException
from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table
from rich.text import Text
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.client import RotatingSpotify
from spotify_manager.client import SpotifyClientConfigurationError
from spotify_manager.client import SpotifyRedirectURIError
from spotify_manager.client import get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import AmbiguousArtistError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import SpotifyLookupResponseError
from spotify_manager.processors.library_lookups import evaluate_album_live
from spotify_manager.processors.library_lookups import get_live_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_sync
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio
from spotify_manager.routines import discography
from spotify_manager.routines import found_art
from spotify_manager.routines import genre_reveal
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import queue_3
from spotify_manager.routines import recover_removed_albums
from spotify_manager.routines import release_check
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import review_artists as artist_review
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old
from spotify_manager.routines import the_queue
from spotify_manager.routines import upload_library_files as hf_upload
from spotify_manager.routines.convert_library_file import analyse_comparison
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import convert_your_library_file
from spotify_manager.routines.convert_library_file import restore_your_library_from_file
from spotify_manager.routines.count_items import count_artists_in_library
from spotify_manager.routines.monthly_routine import run_monthly_routines
from spotify_manager.settings import Settings


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


def ask_artist_track_choice(
    console: Console,
    artist: object,
    candidates: tuple[artist_review.TrackCandidate, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for one ambiguous ranked track."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(title=f"Choose a track for {getattr(artist, 'name', '')}")
        table.add_column("#", justify="right")
        table.add_column("Track")
        table.add_column("Release")
        table.add_column("Primary artist")
        table.add_column("Rank", justify="right")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.album,
                candidate.primary_artist_name,
                str(candidate.rank),
            )
        console.print(table)
        choices = [str(index) for index in range(1, len(candidates) + 1)]
        response = Prompt.ask(
            "Track number / [s]kip this run / [q]uit",
            choices=[*choices, "s", "q"],
            console=console,
        )
        if response == "s":
            return artist_review.CHOICE_SKIP
        if response == "q":
            return artist_review.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        if progress is not None:
            progress.start()


def ask_artist_release_choice(
    console: Console,
    artist: object,
    candidates: tuple[artist_review.ReleaseCandidate, ...],
    allow_decline: bool,
    progress: Progress | None = None,
) -> str:
    """Prompt for one eligible release, with an optional permanent decline."""
    if progress is not None:
        progress.stop()
    try:
        artist_name = getattr(artist, "name", "")
        if allow_decline:
            action = Prompt.ask(
                f"Add {artist_name} to queue 3?",
                choices=["y", "n", "s", "q"],
                default="n",
                console=console,
            )
            if action == "n":
                return artist_review.CHOICE_DECLINE
            if action == "s":
                return artist_review.CHOICE_SKIP
            if action == "q":
                return artist_review.CHOICE_QUIT

        table = Table(title=f"Choose a release for {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("First track")
        table.add_column("First artist")
        table.add_column("Eligible")
        eligible_indexes: list[int] = []
        artist_id = getattr(artist, "spotify_id", "")
        for index, candidate in enumerate(candidates, start=1):
            eligible = candidate.is_eligible_for(artist_id)
            if eligible:
                eligible_indexes.append(index)
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                candidate.release_date,
                candidate.first_track_name or "No track",
                candidate.first_track_primary_artist_name or "Unknown",
                "yes" if eligible else "no",
                style=None if eligible else "dim",
            )
        console.print(table)
        choices = [str(index) for index in eligible_indexes]
        response = Prompt.ask(
            "Eligible release number / [s]kip this run / [q]uit",
            choices=[*choices, "s", "q"],
            console=console,
        )
        if response == "s":
            return artist_review.CHOICE_SKIP
        if response == "q":
            return artist_review.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        if progress is not None:
            progress.start()


def ask_new_wine_release_choice(
    console: Console,
    source: new_wine.PlaylistTrack,
    candidates: tuple[new_wine.ReleaseCandidate, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for the release that should follow the current release."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(
            title=(
                f"Choose a release for {source.primary_artist_name} after {source.name}"
            )
        )
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Primary artist")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                candidate.release_date,
                str(candidate.total_tracks),
                candidate.primary_artist_name,
            )
        console.print(table)
        choices = [str(index) for index in range(1, len(candidates) + 1)]
        at_album_endpoint = source.release.release_type in {"Album", "EP"}
        if at_album_endpoint:
            response = Prompt.ask(
                "Release number / [f]inish / [s]kip this run / [q]uit",
                choices=[*choices, "f", "s", "q"],
                console=console,
            )
        else:
            response = Prompt.ask(
                "Release number / [d]rop / [s]kip this run / [q]uit",
                choices=[*choices, "d", "s", "q"],
                console=console,
            )
        if response == "f":
            return new_wine.CHOICE_FINISH
        if response == "d":
            return new_wine.CHOICE_DROP
        if response == "s":
            return new_wine.CHOICE_SKIP
        if response == "q":
            return new_wine.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        if progress is not None:
            progress.start()


def ask_new_kids_release_choice(
    console: Console,
    artist_name: str,
    candidates: tuple[new_kids.RankedRelease, ...],
    progress: Progress | None = None,
) -> str:
    """Prompt for the next ranked New Kids release."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(title=f"Choose the next release for {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Popularity", justify="right")
        table.add_column("Top track", justify="right")
        table.add_column("Saved")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                candidate.release_date,
                str(candidate.total_tracks),
                (
                    str(candidate.popularity)
                    if candidate.popularity is not None
                    else "-"
                ),
                (
                    f"#{candidate.top_track_rank}"
                    if candidate.top_track_rank is not None
                    else "-"
                ),
                "yes" if candidate.saved else "-",
            )
        console.print(table)
        choices = [str(index) for index in range(1, len(candidates) + 1)]
        response = Prompt.ask(
            "Release number / [s]kip this run / [q]uit",
            choices=[*choices, "s", "q"],
            console=console,
        )
        if response == "s":
            return new_kids.CHOICE_SKIP
        if response == "q":
            return new_kids.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        if progress is not None:
            progress.start()


def print_album_discovery_decisions(
    console: Console,
    title: str,
    decisions: tuple[new_kids.FlushResult, ...],
) -> None:
    """Render shared New Kids and Queue 2 artist decisions."""
    if not decisions:
        return
    table = Table(title=title)
    table.add_column("Artist")
    table.add_column("Current")
    table.add_column("Release")
    table.add_column("Like")
    table.add_column("Streak", justify="right")
    table.add_column("Action")
    table.add_column("Next")
    action_styles = {
        "advance": "green",
        "next release": "cyan",
        "great discovery": "bold green",
        "unlucky": "yellow",
        "unfollowed": "bold red",
        "skip": "dim",
    }
    for decision in decisions:
        next_item = decision.target_track or "-"
        if (
            decision.target_release
            and decision.target_release != decision.source_release
        ):
            next_item = f"{decision.target_release} - {next_item}"
        table.add_row(
            decision.artist,
            decision.source_track,
            decision.source_release,
            "liked" if decision.current_liked else "unliked",
            str(decision.consecutive_unliked),
            Text(decision.action, style=action_styles[decision.action]),
            next_item,
        )
    console.print(table)


def ask_slow_listening_release_order(
    console: Console,
    release_date: str,
    candidates: tuple[slow_listening.DiscographyRelease, ...],
    progress: Progress | None = None,
) -> tuple[str, ...]:
    """Prompt for chronological order when Spotify dates are identical."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(title=f"Order releases dated {release_date}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Tracks", justify="right")
        table.add_column("Edition")
        table.add_column("Library")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                candidate.release_type,
                str(candidate.total_tracks),
                "plain" if candidate.plain else "decorated",
                "saved" if candidate.saved else "-",
            )
        console.print(table)
        default = ",".join(str(index) for index in range(1, len(candidates) + 1))
        while True:
            response = Prompt.ask(
                "Order as comma-separated release numbers / [q]uit",
                default=default,
                console=console,
            ).strip()
            if response.casefold() == "q":
                raise slow_listening.SlowListeningCancelledError(
                    "Slow Listening flush paused while ordering releases."
                )
            try:
                indexes = tuple(int(value.strip()) for value in response.split(","))
            except ValueError:
                indexes = ()
            expected = set(range(1, len(candidates) + 1))
            if len(indexes) == len(candidates) and set(indexes) == expected:
                return tuple(candidates[index - 1].spotify_id for index in indexes)
            console.print(
                "Enter every release number exactly once.",
                style="bold yellow",
            )
    finally:
        if progress is not None:
            progress.start()


def ask_slow_listening_action(
    console: Console,
    source: new_wine.PlaylistTrack,
    target: new_wine.ReleaseTrack,
    target_release: slow_listening.DiscographyRelease,
    progress: Progress | None = None,
) -> str:
    """Ask whether the proposed replacement should be added or skipped."""
    if progress is not None:
        progress.stop()
    try:
        response = Prompt.ask(
            (
                f"Next after {source.primary_artist_name} - {source.name}: "
                f"{target.name} ({target_release.name}). "
                "[a]dd / [s]kip this track / [q]uit"
            ),
            choices=["a", "s", "q"],
            default="a",
            console=console,
        )
        return {
            "a": slow_listening.CHOICE_ADVANCE,
            "s": slow_listening.CHOICE_SKIP,
            "q": slow_listening.CHOICE_QUIT,
        }[response]
    finally:
        if progress is not None:
            progress.start()


def ask_queue_3_release_transition(
    console: Console,
    source: new_wine.PlaylistTrack,
    current_release: slow_listening.DiscographyRelease,
    next_release: slow_listening.DiscographyRelease,
    progress: Progress | None = None,
) -> str:
    """Confirm the next chronological release at a Queue 3 boundary."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(title=f"Queue 3 release boundary: {source.primary_artist_name}")
        table.add_column("Position")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_row(
            "Current",
            current_release.name,
            current_release.release_type,
            current_release.chronology_date,
            str(current_release.total_tracks),
        )
        table.add_row(
            "Next",
            next_release.name,
            next_release.release_type,
            next_release.chronology_date,
            str(next_release.total_tracks),
        )
        console.print(table)
        response = Prompt.ask(
            "Advance to this release?",
            choices=["y", "q"],
            default="y",
            console=console,
        )
        return queue_3.CHOICE_ADVANCE if response == "y" else queue_3.CHOICE_QUIT
    finally:
        if progress is not None:
            progress.start()


def ask_queue_3_composer_playlist(
    console: Console,
    artist_name: str,
    candidates: tuple[queue_3.OwnedPlaylist, ...],
    progress: Progress | None = None,
) -> str:
    """Choose one owned composer playlist when names are ambiguous."""
    if progress is not None:
        progress.stop()
    try:
        table = Table(title=f"Queue 3 composer playlist: {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Owned playlist")
        table.add_column("Tracks", justify="right")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(str(index), candidate.name, str(candidate.total_tracks))
        console.print(table)
        response = Prompt.ask(
            "Use which composer playlist?",
            choices=[*(str(index) for index in range(1, len(candidates) + 1)), "q"],
            default="1",
            console=console,
        )
        if response == "q":
            return queue_3.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        if progress is not None:
            progress.start()


def ask_discography_release_selection(
    console: Console,
    artist: discography.QueueArtist,
    candidates: tuple[discography.CatalogRelease, ...],
    status: Status | None = None,
) -> tuple[str, ...]:
    """Prompt for the exact canonical releases to count for one artist."""
    if status is not None:
        status.stop()
    try:
        table = Table(title=f"Choose releases for {artist.name}")
        table.add_column("#", justify="right")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Tracks", justify="right")
        table.add_column("Saved")
        table.add_column("Default")
        default_indexes: list[int] = []
        for index, release in enumerate(candidates, start=1):
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
        console.print(table)
        default = discography.format_release_indexes(tuple(default_indexes))
        while True:
            response = Prompt.ask(
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
                indexes = discography.parse_release_indexes(
                    response,
                    len(candidates),
                )
            except ValueError:
                console.print(
                    "Enter valid comma-separated numbers or ranges.",
                    style="bold yellow",
                )
                continue
            return tuple(candidates[index - 1].spotify_id for index in indexes)
    finally:
        if status is not None:
            status.start()


def acknowledge_slow_listening_completion(
    console: Console,
    source: new_wine.PlaylistTrack,
    progress: Progress | None = None,
) -> None:
    """Pause after an artist leaves Slow Listening so its slot can be filled."""
    if progress is not None:
        progress.stop()
    try:
        console.print(
            f"{source.primary_artist_name} has completed Slow Listening.",
            style="bold cyan",
        )
        console.input(
            "Add a new artist to the playlist, then press Enter to continue. "
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


def format_file_size(size_bytes: int) -> str:
    """Format a byte count for a compact CLI summary."""
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


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
    if your_library_only and lastfm_only:
        raise typer.BadParameter(
            "use either --your-library-only or --lastfm-only, not both"
        )

    console = Console()
    try:
        with console.status("Validating library exports"):
            plan = hf_upload.prepare_library_files_upload(
                include_your_library=not lastfm_only,
                include_lastfm=not your_library_only,
                repo_id=repo_id,
                revision=revision,
            )
    except hf_upload.LibraryFilesUploadError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    table = Table(title=f"HF upload: {plan.repo_id}@{plan.revision}")
    table.add_column("Export")
    table.add_column("Items", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("HF path")
    for resource in plan.resources:
        table.add_row(
            resource.name,
            f"{resource.item_count:,}",
            format_file_size(resource.size_bytes),
            resource.path_in_repo,
        )
    if plan.lastfm_parts:
        table.add_row(
            f"{len(plan.lastfm_parts)} inline Last.fm fallback parts",
            "",
            format_file_size(sum(len(part.content) for part in plan.lastfm_parts)),
            f"{hf_upload.REMOTE_FILES_DIR}/{hf_upload.LASTFM_PART_PREFIX}*",
            style="dim",
        )
    console.print(table)

    if dry_run:
        console.print(
            f"Dry run complete: {plan.upload_file_count} files validated; "
            "nothing was changed.",
            style="bold green",
        )
        return

    try:
        with console.status("Uploading library exports to Hugging Face"):
            result = hf_upload.upload_library_files(plan)
    except hf_upload.LibraryFilesUploadError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    console.print(
        f"Uploaded {result.uploaded_files} files "
        f"({format_file_size(result.upload_size_bytes)}).",
        style="bold green",
    )
    if result.deleted_stale_parts:
        console.print(
            f"Removed {result.deleted_stale_parts} obsolete fallback parts.",
            style="yellow",
        )
    console.print(f"HF commit: {result.commit_url}", markup=False)
    console.print("The Space rebuild has been triggered.", style="dim")


def print_scrobble_selection_table(
    console: Console,
    title: str,
    results: tuple[blast_from_past.SpotifySelectionResult, ...],
) -> None:
    """Print Last.fm selections and their Spotify outcomes."""
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Date")
    table.add_column("Rule")
    table.add_column("Last.fm scrobble")
    table.add_column("Spotify match")
    table.add_column("Result")
    action_styles = {
        "added": "bold green",
        "already present": "green",
        "duplicate selection": "yellow",
        "no match": "bold red",
    }
    for number, result in enumerate(results, start=1):
        selection = result.selection
        album = selection.scrobble.album or "(no album)"
        scrobble_text = (
            f"{selection.scrobble.artist} - {selection.scrobble.track} - {album}"
        )
        if result.match is None:
            match_text = Text("No qualifying result", style="red")
        else:
            match_album = result.match.album or "(no album)"
            liked = "liked" if result.match.liked else "unliked"
            album_score = (
                "n/a"
                if result.match.album_similarity is None
                else f"{result.match.album_similarity:.0%}"
            )
            match_text = Text(
                f"{', '.join(result.match.artists)} - {result.match.track} - "
                f"{match_album}\n{liked}; track {result.match.track_similarity:.0%}, "
                f"album {album_score}; {result.qualifying_matches} qualified"
            )
        table.add_row(
            str(number),
            selection.selected_date.isoformat(),
            f"page {selection.page}/{selection.total_pages}, "
            f"{selection.direction}, #{selection.position}",
            Text(scrobble_text),
            match_text,
            Text(result.action, style=action_styles[result.action]),
        )
    console.print(table)


def print_found_art_table(
    console: Console,
    results: tuple[found_art.FoundArtResult, ...],
) -> None:
    """Print ranked Last.fm candidates and their Spotify outcomes."""
    table = Table(title="Found Art")
    table.add_column("#", justify="right")
    table.add_column("Last.fm candidate")
    table.add_column("Recommendation")
    table.add_column("Spotify match")
    table.add_column("Result")
    action_styles = {
        "added": "bold green",
        "would add": "bold cyan",
        "already present": "yellow",
        "artist already selected": "yellow",
        "duplicate": "yellow",
        "liked": "magenta",
        "no Spotify match": "bold red",
    }
    for number, result in enumerate(results, start=1):
        candidate = result.candidate
        support_count = len(candidate.supporting_seeds)
        support_text = (
            f"base #{candidate.base_rank}; weekly {candidate.weekly_rank:.3f}; "
            f"score {candidate.score:.3f}; best {candidate.best_match:.0%}; "
            f"{support_count} seed{'s' if support_count != 1 else ''}"
        )
        if result.action == "artist already selected":
            match_text = Text("Skipped after this artist was selected", style="yellow")
        elif result.match is None:
            match_text = Text("No unliked qualifying match", style="red")
        else:
            match_text = Text(
                f"{', '.join(result.match.artists)} - {result.match.track}\n"
                f"{result.match.album or '(no album)'}; "
                f"track {result.match.track_similarity:.0%}"
            )
        table.add_row(
            str(number),
            f"{candidate.artist} - {candidate.track}",
            support_text,
            match_text,
            Text(result.action, style=action_styles[result.action]),
        )
    console.print(table)


def print_queue_fill_table(
    console: Console,
    results: tuple[the_queue.FillResult, ...],
) -> None:
    """Render Last.fm artist recommendations resolved for The Queue."""
    table = Table(title="Fill The Queue from Last.fm")
    table.add_column("#", justify="right")
    table.add_column("Last.fm artist")
    table.add_column("Recommendation")
    table.add_column("Spotify selection")
    table.add_column("Result")
    styles = {
        "added": "bold green",
        "would add": "bold cyan",
        "already represented": "yellow",
        "no Spotify match": "bold red",
        "no unliked top track": "magenta",
        "skipped": "yellow",
    }
    for index, result in enumerate(results, start=1):
        recommendation = result.recommendation
        detail = (
            f"base #{recommendation.base_rank}; "
            f"weekly {recommendation.weekly_rank:.3f}; "
            f"score {recommendation.score:.3f}; "
            f"{len(recommendation.supporting_seeds)} seeds"
        )
        if result.spotify_artist is None:
            selection = "No Spotify mapping"
        elif result.track is None:
            selection = result.spotify_artist.name
        else:
            follow_note = " · follow" if result.followed else ""
            selection = (
                f"{result.spotify_artist.name} - {result.track.name}{follow_note}"
            )
        table.add_row(
            str(index),
            recommendation.artist,
            detail,
            selection,
            Text(result.action, style=styles[result.action]),
        )
    console.print(table)


def print_queue_flush_table(
    console: Console,
    results: tuple[the_queue.FlushResult, ...],
) -> None:
    """Render Queue top-track transitions and live-like decisions."""
    table = Table(title="Flush The Queue")
    table.add_column("Artist")
    table.add_column("Current")
    table.add_column("Likes", justify="right")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column("Reason")
    styles = {
        "advance": "cyan",
        "promote": "bold green",
        "unlucky": "yellow",
        "unfollow": "bold red",
        "blocked": "bold magenta",
    }
    for result in results:
        target = result.target_track or "-"
        if result.target_release:
            target += f" · {result.target_release}"
        table.add_row(
            result.artist,
            result.source_track,
            (
                f"top {result.top_liked_tracks}/{result.top_tracks}; "
                f"total {result.total_liked_tracks}"
            ),
            Text(result.action, style=styles[result.action]),
            target,
            result.reason or "-",
        )
    console.print(table)


def print_scrobble_history_summary(
    console: Console,
    summary: scrobble_history.ScrobbleHistorySummary,
) -> None:
    """Render one compact Last.fm history refresh summary."""
    table = Table(title="Last.fm scrobble history")
    table.add_column("Source")
    table.add_column("Scrobbles", justify="right")
    table.add_row("Existing export", f"{summary.export_scrobbles:,}")
    table.add_row("Legacy Found Art delta", f"+{summary.legacy_scrobbles_added:,}")
    table.add_row("Live Last.fm API", f"+{summary.live_scrobbles_added:,}")
    table.add_row("Merged total", f"{summary.total_scrobbles:,}", style="bold")
    console.print(table)
    if summary.dry_run:
        console.print("Dry run: the canonical history was not changed.", style="cyan")
    elif summary.persisted:
        console.print(
            f"Saved atomically after backup: {summary.backup_path}",
            style="bold green",
            markup=False,
        )
    else:
        console.print("The canonical history was already current.", style="green")


def _scrobble_date(timestamp_ms: int) -> str:
    """Format one Last.fm timestamp in the listening timezone."""
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        blast_from_past.SCROBBLE_TIMEZONE,
    ).strftime("%Y-%m-%d")


def ask_something_old_artist(
    console: Console,
    artist_name: str,
    candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    status: Status,
) -> str:
    """Prompt when Spotify has several exact-name artist matches."""
    status.stop()
    try:
        table = Table(title=f"Choose the Spotify artist for {artist_name}")
        table.add_column("#", justify="right")
        table.add_column("Artist")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                str(candidate.popularity) if candidate.popularity is not None else "?",
                (
                    f"{candidate.followers:,}"
                    if candidate.followers is not None
                    else "?"
                ),
                candidate.spotify_id,
            )
        console.print(table)
        response = Prompt.ask(
            "Artist number or (q)uit",
            choices=[*(str(index) for index in range(1, len(candidates) + 1)), "q"],
            default="q",
            console=console,
        )
        return "quit" if response == "q" else candidates[int(response) - 1].spotify_id
    finally:
        status.start()


def ask_release_check_artist(
    console: Console,
    artist: release_check.RankedArtist,
    candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    progress: Progress,
) -> str:
    """Prompt for one ambiguous Last.fm-to-Spotify artist mapping."""
    progress.stop()
    try:
        table = Table(
            title=(
                f"Map Last.fm artist #{artist.rank}: {artist.name} "
                f"({artist.scrobbles:,} scrobbles)"
            )
        )
        table.add_column("#", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Exact")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        if not candidates:
            console.print(
                f"No Spotify artists matched the current search for {artist.name}.",
                style="bold yellow",
            )
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                "yes" if candidate.exact_name else "no",
                str(candidate.popularity) if candidate.popularity is not None else "?",
                (
                    f"{candidate.followers:,}"
                    if candidate.followers is not None
                    else "?"
                ),
                candidate.spotify_id,
                style=None if candidate.exact_name else "dim",
            )
        console.print(table)
        response = Prompt.ask(
            (
                "Artist number / [n]ew search / [s]kip this run / "
                "[p]ermanently skip / [q]uit and resume later"
            ),
            choices=[
                *(str(index) for index in range(1, len(candidates) + 1)),
                "n",
                "s",
                "p",
                "q",
            ],
            default="s",
            console=console,
        )
        if response == "n":
            while True:
                search_text = Prompt.ask(
                    "New Spotify artist search",
                    console=console,
                ).strip()
                if search_text:
                    return f"{release_check.CHOICE_SEARCH_PREFIX}{search_text}"
                console.print("Search text cannot be empty.", style="bold yellow")
        if response == "s":
            return release_check.CHOICE_SKIP
        if response == "p":
            return release_check.CHOICE_SKIP_ARTIST
        if response == "q":
            return release_check.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        progress.start()


def ask_queue_artist(
    console: Console,
    recommendation: the_queue.ArtistRecommendation,
    candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    progress: Progress,
) -> str:
    """Prompt for an ambiguous Last.fm Queue artist mapping."""
    progress.stop()
    try:
        table = Table(title=f"Map Queue artist: {recommendation.artist}")
        table.add_column("#", justify="right")
        table.add_column("Spotify artist")
        table.add_column("Exact")
        table.add_column("Popularity", justify="right")
        table.add_column("Followers", justify="right")
        table.add_column("Spotify id")
        if not candidates:
            console.print(
                f"No Spotify artists matched {recommendation.artist}.",
                style="bold yellow",
            )
        for index, candidate in enumerate(candidates, start=1):
            table.add_row(
                str(index),
                candidate.name,
                "yes" if candidate.exact_name else "no",
                str(candidate.popularity) if candidate.popularity is not None else "?",
                (
                    f"{candidate.followers:,}"
                    if candidate.followers is not None
                    else "?"
                ),
                candidate.spotify_id,
                style=None if candidate.exact_name else "dim",
            )
        console.print(table)
        response = Prompt.ask(
            "Artist number / [n]ew search / [s]kip this run / [q]uit",
            choices=[
                *(str(index) for index in range(1, len(candidates) + 1)),
                "n",
                "s",
                "q",
            ],
            default="s",
            console=console,
        )
        if response == "n":
            while True:
                search_text = Prompt.ask("New Spotify artist search", console=console)
                if search_text.strip():
                    return f"{the_queue.CHOICE_SEARCH_PREFIX}{search_text.strip()}"
                console.print("Search text cannot be empty.", style="bold yellow")
        if response == "s":
            return the_queue.CHOICE_SKIP
        if response == "q":
            return the_queue.CHOICE_QUIT
        return candidates[int(response) - 1].spotify_id
    finally:
        progress.start()


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
    progress.stop()
    try:
        tags = release_check.release_tags(release)
        table = Table(title=f"Review release from #{artist.rank} {artist.name}")
        table.add_column("Release")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("First track")
        table.add_column("Destinations")
        table.add_row(
            release.name,
            " / ".join((release.release_type, *tags)),
            release.release_date,
            track.name,
            ", ".join(destinations),
            style="bold yellow" if tags else None,
        )
        console.print(table)
        prompt = "[a]dd / [s]kip permanently / [q]uit and resume later"
        choices = ["a", "s", "q"]
        default = "a"
        if unattached_single:
            prompt = (
                "[a]dd to Wine Cellar / keep [p]ending / "
                "[s]kip permanently / [q]uit and resume later"
            )
            choices.insert(1, "p")
            default = "p"
        response = Prompt.ask(prompt, choices=choices, default=default, console=console)
        return {
            "a": release_check.CHOICE_ADD,
            "p": release_check.CHOICE_PENDING,
            "s": release_check.CHOICE_SKIP,
            "q": release_check.CHOICE_QUIT,
        }[response]
    finally:
        progress.start()


def print_release_check_summary(
    console: Console,
    summary: release_check.ReleaseCheckSummary,
) -> None:
    """Render the release window and every discovered release decision."""
    if summary.history_refresh is not None:
        print_scrobble_history_summary(console, summary.history_refresh)

    table = Table(
        title=(
            "Release check · "
            f"{summary.checked_from.isoformat()} through "
            f"{summary.checked_through.isoformat()}"
        )
    )
    table.add_column("Artist")
    table.add_column("Release")
    table.add_column("Date")
    table.add_column("First track")
    table.add_column("Wine Cellar")
    table.add_column("New Vintage")
    table.add_column("Note")
    action_styles = {
        "added": "bold green",
        "would add": "bold cyan",
        "already present": "yellow",
        "duplicate selection": "yellow",
        "not applicable": "dim",
    }
    for result in summary.results:
        note = result.reason or (
            f"part of upcoming {result.linked_future_release}"
            if result.linked_future_release
            else ""
        )
        table.add_row(
            f"#{result.artist_rank} {result.artist}\n{result.artist_scrobbles:,} plays",
            f"{result.release}\n{result.release_type}",
            result.release_date,
            result.first_track or "-",
            Text(
                result.wine_cellar_action,
                style=action_styles[result.wine_cellar_action],
            ),
            Text(
                result.new_vintage_action,
                style=action_styles[result.new_vintage_action],
            ),
            note,
        )
    console.print(table)

    mode = "Dry run" if summary.dry_run else "Release check"
    resumed = " · resumed" if summary.resumed else ""
    console.print(
        f"{mode}{resumed}: {summary.artists_processed}/{summary.artists_total} "
        f"artists complete; {len(summary.results)} release decision(s).",
        style="bold cyan" if summary.dry_run else "bold green",
    )
    if summary.dry_run:
        console.print(
            "Spotify, release decisions, and the audit log were unchanged. "
            "Last.fm history, artist mappings, and permanent artist skips "
            "were persisted.",
            style="cyan",
        )
    else:
        console.print(
            f"Added {summary.wine_cellar_added} track(s) to Wine Cellar and "
            f"{summary.new_vintage_added} to New Vintage.",
            style="green",
        )
    if summary.paused:
        message = (
            "Dry run stopped; release decisions were not saved."
            if summary.dry_run
            else "Release check paused. Rerun the command to resume here."
        )
        console.print(message, style="bold yellow")


def ask_something_old_mode(
    console: Console,
    artist: something_old.GoldenOldieArtist,
    spotify_artist: something_old.SpotifyArtistCandidate,
    status: Status,
) -> str:
    """Prompt for Last.fm tracks, Spotify tracks, or one album/EP."""
    status.stop()
    try:
        console.print(
            f"[bold]{artist.artist}[/bold] · {artist.scrobbles:,} scrobbles · "
            f"average {_scrobble_date(artist.average_scrobble_ms)} · "
            f"Spotify: {spotify_artist.name}"
        )
        table = Table(title="Something Old selection")
        table.add_column("#", justify="right")
        table.add_column("Source")
        table.add_column("What will be added")
        table.add_row("1", "Last.fm", "Up to 10 most-scrobbled tracks")
        table.add_row("2", "Spotify", "Up to 10 current popular tracks")
        table.add_row("3", "Catalog", "One complete studio album or EP")
        console.print(table)
        response = Prompt.ask(
            "Selection or (q)uit",
            choices=["1", "2", "3", "q"],
            default="1",
            console=console,
        )
        return {
            "1": "lastfm_top_tracks",
            "2": "spotify_top_tracks",
            "3": "album",
            "q": "quit",
        }[response]
    finally:
        status.start()


def ask_something_old_album(
    console: Console,
    artist: something_old.GoldenOldieArtist,
    releases: tuple[slow_listening.DiscographyRelease, ...],
    status: Status,
) -> str:
    """Prompt for one chronologically displayed studio album or EP."""
    status.stop()
    try:
        table = Table(title=f"Albums and EPs by {artist.artist}")
        table.add_column("#", justify="right")
        table.add_column("Date")
        table.add_column("Type")
        table.add_column("Release")
        table.add_column("Tracks", justify="right")
        table.add_column("Edition")
        for index, release in enumerate(releases, start=1):
            edition = (
                "saved" if release.saved else "plain" if release.plain else "other"
            )
            table.add_row(
                str(index),
                release.chronology_date,
                release.release_type,
                release.name,
                str(release.total_tracks),
                edition,
            )
        console.print(table)
        response = Prompt.ask(
            "Release number or (q)uit",
            choices=[*(str(index) for index in range(1, len(releases) + 1)), "q"],
            default="q",
            console=console,
        )
        return "quit" if response == "q" else releases[int(response) - 1].spotify_id
    finally:
        status.start()


def print_something_old_summary(
    console: Console,
    summary: something_old.SomethingOldSummary,
) -> None:
    """Render Golden Oldies context and the selected Spotify tracks."""
    if summary.action == "playlist not empty":
        console.print(
            f"Something Old already contains {summary.playlist_length_before} "
            "item(s); nothing was changed.",
            style="yellow",
        )
        return
    if summary.history_refresh is not None:
        print_scrobble_history_summary(console, summary.history_refresh)
    if summary.ranking_preview:
        ranking = Table(title="Golden Oldies · oldest average scrobble dates")
        ranking.add_column("#", justify="right")
        ranking.add_column("Artist")
        ranking.add_column("Scrobbles", justify="right")
        ranking.add_column("Average date")
        for index, artist in enumerate(summary.ranking_preview, start=1):
            ranking.add_row(
                str(index),
                artist.artist,
                f"{artist.scrobbles:,}",
                _scrobble_date(artist.average_scrobble_ms),
            )
        console.print(ranking)
    if summary.action == "cancelled":
        console.print(
            "Something Old was cancelled; Spotify was unchanged.", style="yellow"
        )
        return

    selection = Table(title="Something Old playlist selection")
    selection.add_column("#", justify="right")
    selection.add_column("Track")
    selection.add_column("Release")
    selection.add_column("Source")
    selection.add_column("Last.fm", justify="right")
    for index, track in enumerate(summary.tracks, start=1):
        selection.add_row(
            str(index),
            f"{', '.join(track.artists)} - {track.track}",
            track.album or "(no album)",
            track.source,
            (str(track.lastfm_scrobbles) if track.lastfm_scrobbles is not None else ""),
        )
    console.print(selection)
    if summary.dry_run:
        console.print(
            f"Dry run: would add {len(summary.tracks)} track(s); "
            "Spotify and local files were unchanged.",
            style="bold cyan",
        )
    else:
        console.print(
            f"Something Old: {summary.playlist_length_before} -> "
            f"{summary.playlist_length_after}; added {len(summary.tracks)} track(s).",
            style="bold green",
        )


@app.command(name="update-scrobble-history")
def update_scrobble_history_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Fetch and report new scrobbles without changing local files.",
    ),
) -> None:
    """Update the canonical Last.fm export used by every history routine."""
    console = Console()
    configuration = Settings()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    lastfm_client = LastFmClient(
        api_key,
        username,
        event_callback=lambda message: console.print(message, style="yellow"),
    )
    try:
        with console.status("Refreshing Last.fm scrobble history") as status:
            summary = scrobble_history.refresh_scrobble_history(
                lastfm_client,
                expected_username=username,
                dry_run=dry_run,
                progress_callback=status.update,
            )
    except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    print_scrobble_history_summary(console, summary)


@app.command(name="something-old")
def something_old_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve and display the selection without changing files or Spotify.",
    ),
) -> None:
    """Fill an empty Something Old slot from Last.fm Golden Oldies."""
    console = Console()
    configuration = Settings()
    try:
        playlist_id = something_old.parse_playlist_id(
            configuration.something_old_new_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (
        something_old.SomethingOldConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    lastfm_client = LastFmClient(
        api_key,
        username,
        event_callback=lambda message: console.print(message, style="yellow"),
    )
    try:
        with console.status("Preparing Something Old") as status:
            summary = something_old.run_something_old(
                client(),
                lastfm_client,
                playlist_id,
                expected_username=username,
                artist_choice_reader=lambda artist, candidates: (
                    ask_something_old_artist(
                        console,
                        artist.artist,
                        candidates,
                        status,
                    )
                ),
                mode_reader=lambda artist, spotify_artist: ask_something_old_mode(
                    console,
                    artist,
                    spotify_artist,
                    status,
                ),
                album_choice_reader=lambda artist, releases: ask_something_old_album(
                    console,
                    artist,
                    releases,
                    status,
                ),
                dry_run=dry_run,
                progress_callback=status.update,
            )
    except (
        something_old.SomethingOldError,
        scrobble_history.ScrobbleHistoryError,
        LastFmError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc
    print_something_old_summary(console, summary)


@app.command(name="check-new-releases")
def check_new_releases_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Show release decisions without changing playlists; Last.fm history "
            "and artist mapping choices are still persisted."
        ),
    ),
) -> None:
    """Check Last.fm's most-played artists for newly released music."""
    console = Console()
    configuration = Settings()
    try:
        playlists = release_check.ReleaseCheckPlaylists.from_references(
            configuration.wine_cellar_playlist,
            configuration.new_vintage_playlist,
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (
        release_check.ReleaseCheckConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    lastfm_client = LastFmClient(
        api_key,
        username,
        event_callback=lambda message: console.print(message, style="yellow"),
    )
    progress_ref: Progress | None = None
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
            task = progress.add_task("Preparing release check", total=None)

            def update_progress(
                completed: int,
                total: int,
                status: str,
            ) -> None:
                progress.update(
                    task,
                    completed=completed,
                    total=total or None,
                    description=status,
                )

            def choose_release(
                artist: release_check.RankedArtist,
                release: release_check.ReleaseCandidate,
                track: release_check.ReleaseTrack,
                destinations: tuple[str, ...],
                unattached: bool,
            ) -> str:
                return ask_release_check_release(
                    console,
                    artist,
                    release,
                    track,
                    destinations,
                    unattached,
                    progress,
                )

            summary = release_check.run_release_check(
                client(),
                lastfm_client,
                playlists,
                expected_username=username,
                artist_choice_reader=lambda artist, candidates: (
                    ask_release_check_artist(
                        console,
                        artist,
                        candidates,
                        progress,
                    )
                ),
                release_choice_reader=choose_release,
                dry_run=dry_run,
                progress_callback=update_progress,
            )
    except KeyboardInterrupt as exc:
        if dry_run:
            console.print("Dry run cancelled; nothing was changed.", style="yellow")
        else:
            console.print(
                "Release check paused. Progress was saved; rerun to resume.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc
    except (
        release_check.ReleaseCheckError,
        scrobble_history.ScrobbleHistoryError,
        LastFmError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        if not dry_run:
            console.print(
                "Completed artist and release boundaries remain saved.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        if not dry_run:
            console.print(
                "Release-check progress was saved; rerun to resume.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc
    except RequestException as exc:
        console.print(
            f"Spotify connection failed: {exc}",
            style="bold red",
            markup=False,
        )
        if not dry_run:
            console.print(
                "Release-check progress was saved; rerun to resume.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc
    finally:
        if progress_ref is not None:
            progress_ref.stop()

    print_release_check_summary(console, summary)


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
    console = Console()
    if count is not None and max_playlist_length is not None:
        raise typer.BadParameter(
            "use either --count or --max-playlist-length, not both"
        )

    configuration = Settings()
    try:
        playlist_id = found_art.parse_found_art_playlist_id(
            configuration.found_art_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    effective_count = (
        found_art.DEFAULT_COUNT
        if count is None and max_playlist_length is None
        else count
    )
    lastfm_client = LastFmClient(
        api_key,
        username,
        event_callback=lambda message: console.print(message, style="yellow"),
    )
    try:
        with console.status("Preparing Found Art recommendations") as status:
            summary = found_art.run_found_art(
                client(),
                lastfm_client,
                playlist_id,
                count=effective_count,
                max_playlist_length=max_playlist_length,
                seed_count=seed_count,
                dry_run=dry_run,
                progress_callback=status.update,
            )
    except (found_art.FoundArtError, LastFmError) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    print_found_art_table(console, summary.results)
    console.print(
        f"Listening week: {summary.week_start.isoformat()} through "
        f"{(summary.week_start + timedelta(days=6)).isoformat()}",
        style="bold cyan",
    )
    console.print(
        f"History: {summary.history_scrobbles:,} scrobbles across "
        f"{summary.history_tracks:,} tracks; "
        f"{summary.live_scrobbles_added:,} new live scrobbles.",
        style="dim",
    )
    console.print(
        f"Recommendations: {summary.seed_count} seeds produced "
        f"{summary.candidate_count:,} unheard candidates.",
        style="dim",
    )
    if summary.dry_run:
        console.print(
            f"Dry run: selected {summary.selected} of "
            f"{summary.requested_count} requested tracks; Spotify was unchanged.",
            style="bold cyan",
        )
    else:
        console.print(
            f"Playlist: {summary.playlist_length_before} -> "
            f"{summary.playlist_length_after} items; added {summary.added} of "
            f"{summary.requested_count} requested tracks.",
            style="bold",
        )


def configured_queue_playlists(configuration: Settings) -> the_queue.QueuePlaylists:
    """Parse every playlist used by The Queue's fill and flush commands."""
    return the_queue.QueuePlaylists.from_references(
        configuration.the_queue_playlist,
        configuration.the_queue_2_playlist,
        configuration.new_kids_on_the_block_playlist,
        configuration.the_queue_3_playlist,
        configuration.unlucky_ones_playlist,
    )


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
        False,
        "--dry-run",
        help="Resolve recommendations without changing Spotify.",
    ),
) -> None:
    """Recommend unheard artists from Last.fm and add them to The Queue."""
    if count is not None and max_playlist_length is not None:
        raise typer.BadParameter(
            "use either --count or --max-playlist-length, not both"
        )
    console = Console()
    configuration = Settings()
    try:
        playlists = configured_queue_playlists(configuration)
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (the_queue.QueueConfigError, found_art.FoundArtConfigError) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    effective_count = (
        the_queue.DEFAULT_COUNT
        if count is None and max_playlist_length is None
        else count
    )
    progress_ref: Progress | None = None

    def echo(line: str = "") -> None:
        style = None
        if line.startswith(("Added", "Recorded", "Updated")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    lastfm_client = LastFmClient(
        api_key,
        username,
        event_callback=lambda message: console.print(message, style="yellow"),
    )
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
            description = "Building Last.fm artist recommendations"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total) or None,
                    description=status,
                )

            summary = the_queue.fill_queue_from_lastfm(
                review_client(),
                lastfm_client,
                playlists,
                choice_reader=lambda recommendation, candidates: ask_queue_artist(
                    console,
                    recommendation,
                    candidates,
                    progress,
                ),
                count=effective_count,
                max_playlist_length=max_playlist_length,
                seed_count=seed_count,
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except (
        the_queue.QueueError,
        release_check.ReleaseCheckError,
        LastFmError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print(
            "Queue fill stopped safely. Cached calls and completed additions "
            "remain saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    finally:
        if progress_ref is not None:
            progress_ref.stop()

    print_queue_fill_table(console, summary.results)
    console.print(
        f"Listening week: {summary.week_start.isoformat()} through "
        f"{(summary.week_start + timedelta(days=6)).isoformat()}",
        style="bold cyan",
    )
    prefix = "Dry run" if summary.dry_run else "Fill"
    console.print(
        f"{prefix}: {summary.history_scrobbles:,} scrobbles across "
        f"{summary.history_artists:,} artists; {summary.seed_count} seeds, "
        f"{summary.candidate_count:,} candidates; Queue "
        f"{summary.playlist_length_before} -> {summary.playlist_length_after}; "
        f"selected {summary.selected}/{summary.requested_count}.",
        style="bold",
    )
    if summary.paused:
        console.print("Queue fill paused; rerun to continue.", style="bold yellow")


@app.command(name="flush-queue")
def flush_queue_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Plan the first ten Queue artists without changing Spotify or state.",
    ),
) -> None:
    """Advance the first ten Queue artists through Spotify's top tracks."""
    console = Console()
    progress_ref: Progress | None = None
    try:
        playlists = configured_queue_playlists(Settings())
    except the_queue.QueueConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith(("Advanced", "Promoted", "Added")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("Unfollowed"):
            style = "bold red"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning The Queue flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = the_queue.flush_queue(
                review_client(),
                playlists,
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "The active Queue flush was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "The active Queue flush was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except the_queue.QueueError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        console.print(
            "The active Queue flush was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print(
            "Queue flush paused. The active run was saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    finally:
        if progress_ref is not None:
            progress_ref.stop()

    print_queue_flush_table(console, summary.results)
    prefix = "Dry run" if summary.dry_run else "Flush"
    console.print(
        f"{prefix}: Queue {summary.playlist_length_before} -> "
        f"{summary.playlist_length_after}; processed "
        f"{summary.processed}/{summary.total} artists.",
        style="bold",
    )
    if summary.resumed:
        console.print("Resumed the previously saved Queue flush.", style="cyan")


@app.command(name="flush-new-kids")
def flush_new_kids_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the complete run without changing Spotify or durable state.",
    ),
) -> None:
    """Advance New Kids artists and refill the playlist from Queue 2."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        new_kids_playlist_id = new_kids.parse_playlist_id(
            configuration.new_kids_on_the_block_playlist,
            "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
        )
        queue_2_playlist_id = new_kids.parse_playlist_id(
            configuration.the_queue_2_playlist,
            "THE_QUEUE_2_PLAYLIST",
        )
        great_discoveries_playlist_id = new_kids.parse_playlist_id(
            configuration.great_discoveries_2026_playlist,
            "GREAT_DISCOVERIES_2026_PLAYLIST",
        )
        unlucky_ones_playlist_id = new_kids.parse_playlist_id(
            configuration.unlucky_ones_playlist,
            "UNLUCKY_ONES_PLAYLIST",
        )
        newfoundland_playlist_id = new_kids.parse_playlist_id(
            configuration.discography_newfoundland_playlist,
            "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
        )
    except new_kids.NewKidsConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith(("Added", "Moved", "Removed", "Saved", "Reconciled")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith(("Unfollowed", "Unsaved")):
            style = "bold red"
        elif "resum" in line.casefold():
            style = "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning New Kids flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = new_kids.flush_new_kids(
                review_client(),
                new_kids_playlist_id,
                queue_2_playlist_id,
                great_discoveries_playlist_id,
                unlucky_ones_playlist_id,
                newfoundland_playlist_id,
                choice_reader=lambda artist, candidates: ask_new_kids_release_choice(
                    console,
                    artist,
                    candidates,
                    progress_ref,
                ),
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        if not dry_run:
            console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        if not dry_run:
            console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc
    except new_kids.NewKidsError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        if not dry_run:
            console.print(
                "The active New Kids run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        if not dry_run:
            console.print(
                "New Kids flush paused. The active run was saved.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc

    print_album_discovery_decisions(
        console,
        "New Kids on the Block",
        summary.results,
    )

    transfers = [("Before", transfer) for transfer in summary.prefill] + [
        ("After", transfer) for transfer in summary.postfill
    ]
    if transfers:
        transfer_table = Table(title="Queue 2 transfer")
        transfer_table.add_column("Stage")
        transfer_table.add_column("Artist")
        transfer_table.add_column("Track")
        transfer_table.add_column("Action")
        for stage, transfer in transfers:
            transfer_table.add_row(
                stage,
                transfer.artist,
                transfer.track,
                transfer.action,
            )
        console.print(transfer_table)

    prefix = "Dry run" if summary.dry_run else "Flush"
    console.print(
        f"{prefix}: New Kids {summary.playlist_length_before} -> "
        f"{summary.playlist_length_after}; {len(summary.results)} decisions, "
        f"{len(summary.prefill) + len(summary.postfill)} Queue 2 transfers.",
        style="bold",
    )
    if summary.resumed:
        console.print("Resumed the previously saved flush.", style="cyan")
    if summary.paused:
        console.print(
            "Flush paused; run the command again to resume.",
            style="bold yellow",
        )


@app.command(name="flush-queue-2")
def flush_queue_2_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the Queue 2 run without changing Spotify or durable state.",
    ),
) -> None:
    """Fill New Kids, then advance the first ten Queue 2 artists."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        new_kids_playlist_id = new_kids.parse_playlist_id(
            configuration.new_kids_on_the_block_playlist,
            "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
        )
        queue_2_playlist_id = new_kids.parse_playlist_id(
            configuration.the_queue_2_playlist,
            "THE_QUEUE_2_PLAYLIST",
        )
        great_discoveries_playlist_id = new_kids.parse_playlist_id(
            configuration.great_discoveries_2026_playlist,
            "GREAT_DISCOVERIES_2026_PLAYLIST",
        )
        unlucky_ones_playlist_id = new_kids.parse_playlist_id(
            configuration.unlucky_ones_playlist,
            "UNLUCKY_ONES_PLAYLIST",
        )
        newfoundland_playlist_id = new_kids.parse_playlist_id(
            configuration.discography_newfoundland_playlist,
            "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
        )
    except new_kids.NewKidsConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith(("Added", "Moved", "Removed", "Saved", "Reconciled")):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith(("Unfollowed", "Unsaved")):
            style = "bold red"
        elif "resum" in line.casefold():
            style = "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning Queue 2 flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = new_kids.flush_queue_2(
                review_client(),
                new_kids_playlist_id,
                queue_2_playlist_id,
                great_discoveries_playlist_id,
                unlucky_ones_playlist_id,
                newfoundland_playlist_id,
                choice_reader=lambda artist, candidates: ask_new_kids_release_choice(
                    console,
                    artist,
                    candidates,
                    progress_ref,
                ),
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        if not dry_run:
            console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        if not dry_run:
            console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=0) from exc
    except new_kids.NewKidsError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        if not dry_run:
            console.print(
                "The active Queue 2 run was saved and can be resumed.",
                style="yellow",
            )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        if not dry_run:
            console.print(
                "Queue 2 flush paused. The active run was saved.",
                style="bold yellow",
            )
        raise typer.Exit(code=0) from exc

    print_album_discovery_decisions(console, "The Queue 2", summary.results)
    if summary.prefill:
        transfer_table = Table(title="New Kids prefill")
        transfer_table.add_column("Artist")
        transfer_table.add_column("Track")
        transfer_table.add_column("Action")
        for transfer in summary.prefill:
            transfer_table.add_row(
                transfer.artist,
                transfer.track,
                transfer.action,
            )
        console.print(transfer_table)

    prefix = "Dry run" if summary.dry_run else "Flush"
    console.print(
        f"{prefix}: New Kids {summary.new_kids_length_before} -> "
        f"{summary.new_kids_length_after}; Queue 2 "
        f"{summary.queue_length_before} -> {summary.queue_length_after}; "
        f"{len(summary.results)} decisions, {len(summary.prefill)} transfers.",
        style="bold",
    )
    if summary.resumed:
        console.print("Resumed the previously saved Queue 2 flush.", style="cyan")
    if summary.paused:
        console.print(
            "Flush paused; run the command again to resume.",
            style="bold yellow",
        )


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
        help=("Refill only from artists with 18 liked tracks or 3 saved albums."),
    ),
) -> None:
    """Advance every New Wine track once according to its release."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        new_wine_playlist_id = new_wine.parse_playlist_id(
            configuration.new_wine_from_old_bottles_playlist,
            "NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST",
        )
        sauvignon_playlist_id = new_wine.parse_playlist_id(
            configuration.sauvignon_terre_neuve_playlist,
            "SAUVIGNON_TERRE_NEUVE_PLAYLIST",
        )
        wine_cellar_playlist_id = new_wine.parse_playlist_id(
            configuration.wine_cellar_playlist,
            "WINE_CELLAR_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if (
            line.startswith("Added")
            or line.startswith("Moved")
            or line.startswith("Removed")
        ):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("No ") or "skipping" in line.casefold():
            style = "dim yellow"
        elif line.startswith("Source already removed"):
            style = "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning New Wine flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = new_wine.flush_new_wine(
                review_client(),
                new_wine_playlist_id,
                sauvignon_playlist_id,
                choice_reader=lambda source, candidates: ask_new_wine_release_choice(
                    console,
                    source,
                    candidates,
                    progress_ref,
                ),
                wine_cellar_playlist_id=wine_cellar_playlist_id,
                no_discovery=no_discovery,
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "The active New Wine run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "The active New Wine run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except new_wine.NewWineError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        console.print(
            "The active New Wine run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print(
            "New Wine flush paused. The active run was saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    table = Table(title="New Wine from Old Bottles")
    table.add_column("Artist")
    table.add_column("Current track")
    table.add_column("Release")
    table.add_column("Like")
    table.add_column("Streak", justify="right")
    table.add_column("Action")
    table.add_column("Next")
    action_styles = {
        "advance": "green",
        "drop": "bold red",
        "sauvignon": "bold cyan",
        "complete single": "cyan",
        "skip": "yellow",
    }
    for result in summary.results:
        action = str(result.action)
        drop_labels = {
            "three_consecutive_unliked": "3 unliked",
            "manual_selection": "chosen",
            "only_current_year_single": "only current-year single",
        }
        if result.action == "drop" and result.drop_reason:
            action += f" ({drop_labels.get(result.drop_reason, result.drop_reason)})"
        if result.advance_reason == "next_liked_track":
            action += " (next liked)"
        if result.album_unsaved:
            action += " + unsaved"
        next_track = result.target_track or "-"
        if result.continuation_track:
            next_track = f"{result.continuation_release} - {result.continuation_track}"
        table.add_row(
            result.artist,
            result.source_track,
            f"{result.release} ({result.release_type})",
            "liked" if result.current_liked else "unliked",
            str(result.consecutive_unliked),
            Text(action, style=action_styles[result.action]),
            next_track,
        )
    console.print(table)
    if summary.refill is not None:
        refill_table = Table(title="Wine Cellar refill")
        refill_table.add_column("Artist")
        refill_table.add_column("Track")
        refill_table.add_column("Action")
        refill_table.add_column("Liked", justify="right")
        refill_table.add_column("Albums", justify="right")
        displayed_results = [
            result for result in summary.refill.results if result.action != "ineligible"
        ]
        for refill_result in displayed_results:
            refill_table.add_row(
                refill_result.artist,
                refill_result.source_track,
                refill_result.action,
                (
                    str(refill_result.liked_tracks)
                    if refill_result.liked_tracks is not None
                    else "-"
                ),
                (
                    str(refill_result.saved_albums)
                    if refill_result.saved_albums is not None
                    else "-"
                ),
            )
        if displayed_results:
            console.print(refill_table)
        mode = "no-discovery" if summary.refill.no_discovery else "standard"
        console.print(
            f"Wine Cellar ({mode}): New Wine {summary.refill.before} -> "
            f"{summary.refill.after}; {summary.refill.added} added, "
            f"{summary.refill.removed_from_cellar} removed from Wine Cellar, "
            f"{summary.refill.ineligible} ineligible.",
            style="bold cyan",
        )
    prefix = "Dry run" if summary.dry_run else "Flush"
    album_action = "to unsave" if summary.dry_run else "unsaved"
    console.print(
        f"{prefix}: {summary.processed}/{summary.total} processed; "
        f"{summary.advanced} advanced, {summary.dropped} dropped, "
        f"{summary.sent_to_sauvignon} sent to Sauvignon Terre-Neuve, "
        f"{summary.completed_singles} singles completed, "
        f"{summary.albums_unsaved} albums {album_action}, "
        f"{summary.skipped} skipped.",
        style="bold",
    )
    if summary.resumed:
        console.print("Resumed the previously saved flush.", style="cyan")
    if summary.paused:
        console.print(
            "Flush paused; run the command again to resume.",
            style="bold yellow",
        )


@app.command(name="flush-queue-3")
def flush_queue_3_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Preview the annual import and next ten artist transitions without "
            "changing Spotify or state."
        ),
    ),
) -> None:
    """Advance the first ten Queue 3 artists through studio discographies."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        playlist_id = queue_3.parse_playlist_id(configuration.the_queue_3_playlist)
    except queue_3.Queue3ConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith("Added") or line.startswith("Removed"):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("Completed"):
            style = "bold cyan"
        elif line.startswith("Reconciled") or line.startswith("Imported"):
            style = "cyan"
        elif line.startswith("Skipped"):
            style = "dim yellow"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning Queue 3 flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = queue_3.flush_queue_3(
                review_client(),
                playlist_id,
                transition_reader=lambda source, current, following: (
                    ask_queue_3_release_transition(
                        console,
                        source,
                        current,
                        following,
                        progress_ref,
                    )
                ),
                composer_playlist_reader=lambda artist, candidates: (
                    ask_queue_3_composer_playlist(
                        console,
                        artist,
                        candidates,
                        progress_ref,
                    )
                ),
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "The active Queue 3 run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "The active Queue 3 run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except queue_3.Queue3CancelledError as exc:
        console.print(str(exc), style="bold yellow", markup=False)
        raise typer.Exit(code=0) from exc
    except queue_3.Queue3Error as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        console.print(
            "The active Queue 3 run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print(
            "Queue 3 flush paused. The active run was saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    if summary.annual_import:
        import_table = Table(title="Previous-year Great Discoveries")
        import_table.add_column("Artist")
        import_table.add_column("Track")
        import_table.add_column("Year", justify="right")
        import_table.add_column("Action")
        for seed_result in summary.annual_import:
            import_table.add_row(
                seed_result.artist,
                seed_result.track,
                str(seed_result.source_year),
                seed_result.action,
            )
        console.print(import_table)

    table = Table(title="The Queue 3")
    table.add_column("Artist")
    table.add_column("Current")
    table.add_column("Release")
    table.add_column("Action")
    table.add_column("Next")
    for flush_result in summary.results:
        next_item = flush_result.target_track or "-"
        if (
            flush_result.target_release
            and flush_result.target_release != flush_result.source_release
        ):
            next_item = f"{flush_result.target_release} - {next_item}"
        if flush_result.composer_playlist:
            next_item = f"{flush_result.composer_playlist} - {next_item}"
        action_text = str(flush_result.action)
        if flush_result.album_decision is not None:
            action_text += (
                f"; {flush_result.album_decision} "
                f"{flush_result.album_liked_tracks}/"
                f"{flush_result.album_total_tracks}"
            )
        table.add_row(
            flush_result.artist,
            flush_result.source_track,
            flush_result.source_release,
            action_text,
            next_item,
        )
    console.print(table)
    console.print(
        f"Processed {summary.processed}/{summary.total}: "
        f"{summary.advanced} track advances, "
        f"{summary.changed_releases} release changes, "
        f"{summary.completed_artists} completed artists, "
        f"{summary.skipped} skipped." + (" Preview only." if dry_run else ""),
        style="bold cyan" if dry_run else "bold green",
    )
    if summary.resumed:
        console.print("Resumed the previously saved Queue 3 flush.", style="cyan")
    if summary.paused:
        console.print(
            "Queue 3 flush paused; run the command again to resume.",
            style="bold yellow",
        )


@app.command(name="flush-slow-listening")
def flush_slow_listening_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the next two transitions without changing Spotify or state.",
    ),
) -> None:
    """Advance the first two Slow Listening tracks through studio releases."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        playlist_id = slow_listening.parse_playlist_id(
            configuration.slow_listening_playlist
        )
    except slow_listening.SlowListeningConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith("Added") or line.startswith("Removed"):
            style = "bold green"
        elif line.startswith("Would"):
            style = "yellow"
        elif line.startswith("Completed"):
            style = "bold cyan"
        elif line.startswith("Skipped"):
            style = "dim yellow"
        elif line.startswith("Source already removed"):
            style = "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

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
            description = "Planning Slow Listening flush"
            if dry_run:
                description += " (dry run)"
            task_id = progress.add_task(description, total=None)

            def update_progress(completed: int, total: int, status: str) -> None:
                progress.update(
                    task_id,
                    completed=completed,
                    total=max(completed, total),
                    description=status,
                )

            summary = slow_listening.flush_slow_listening(
                review_client(),
                playlist_id,
                order_reader=lambda release_date, candidates: (
                    ask_slow_listening_release_order(
                        console,
                        release_date,
                        candidates,
                        progress_ref,
                    )
                ),
                completion_notifier=lambda source: (
                    acknowledge_slow_listening_completion(
                        console,
                        source,
                        progress_ref,
                    )
                ),
                action_reader=lambda source, target, target_release: (
                    ask_slow_listening_action(
                        console,
                        source,
                        target,
                        target_release,
                        progress_ref,
                    )
                ),
                dry_run=dry_run,
                echo=echo,
                progress_callback=update_progress,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except slow_listening.SlowListeningCancelledError as exc:
        console.print(str(exc), style="bold yellow", markup=False)
        raise typer.Exit(code=0) from exc
    except slow_listening.SlowListeningError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        console.print(
            "The active Slow Listening run was saved and can be resumed.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print(
            "Slow Listening flush paused. The active run was saved.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc

    table = Table(title="Slow Listening")
    table.add_column("Artist")
    table.add_column("Current")
    table.add_column("Release")
    table.add_column("Action")
    table.add_column("Next")
    action_styles = {
        "advance": "green",
        "complete": "bold cyan",
        "skip": "yellow",
    }
    for result in summary.results:
        action = str(result.action)
        if result.skipped_candidates:
            count = len(result.skipped_candidates)
            action += f" ({count} candidate{'s' if count != 1 else ''} skipped)"
        if result.reason:
            action += f" ({result.reason})"
        table.add_row(
            result.artist,
            result.source_track,
            result.source_release,
            Text(action, style=action_styles[result.action]),
            (
                f"{result.target_track} ({result.target_release})"
                if result.target_track and result.target_release
                else "-"
            ),
        )
    console.print(table)
    prefix = "Dry run" if summary.dry_run else "Flush"
    console.print(
        f"{prefix}: {summary.processed}/{summary.total} processed; "
        f"{summary.advanced} advanced, "
        f"{summary.completed_artists} artists completed, "
        f"{summary.skipped} skipped.",
        style="bold",
    )
    if summary.resumed:
        console.print("Resumed the previously saved flush.", style="cyan")
    if summary.paused:
        console.print(
            "Flush paused; run the command again to resume.",
            style="bold yellow",
        )


@app.command(name="flush-requeue-for-a-dream")
def flush_requeue_for_a_dream_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the next release transition without changing Spotify.",
    ),
) -> None:
    """Advance the first Requeue for a Dream artist by one release."""
    console = Console()
    configuration = Settings()
    try:
        playlist_id = requeue_for_a_dream.parse_playlist_id(
            configuration.reqeueue_for_a_dream_playlist
        )
    except requeue_for_a_dream.RequeueForADreamConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = "bold green" if line.startswith(("Added", "Removed")) else "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    try:
        with console.status(
            "Planning Requeue for a Dream" + (" (dry run)" if dry_run else "")
        ) as status:
            summary = requeue_for_a_dream.flush_requeue_for_a_dream(
                review_client(),
                playlist_id,
                dry_run=dry_run,
                echo=echo,
                progress_callback=status.update,
                retry_call=retry_call,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except requeue_for_a_dream.RequeueForADreamError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    table = Table(title="Requeue for a Dream")
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
    }[summary.action]
    if summary.target_already_present:
        action += " (already present)"
    if summary.reason:
        action += f" ({summary.reason})"
    table.add_row(
        summary.artist or "-",
        summary.source_release or "-",
        action,
        summary.target_release or "-",
        summary.target_track or "-",
    )
    console.print(table)
    console.print(
        f"Playlist: {summary.playlist_length_before} -> "
        f"{summary.playlist_length_after} tracks"
        + (" (preview only)." if dry_run else "."),
        style="bold cyan" if dry_run else "bold green",
    )


def _print_discography_plan(
    console: Console,
    plan: discography.DiscographyPlan,
) -> None:
    """Render one compact discography listening plan."""
    table = Table(title="Next discographies")
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
        console.print("No artists with selected releases were found.", style="yellow")
        return
    summary = (
        f"Total: {plan.total_releases} releases over {plan.days:g} days. "
        f"Next queue: {discography.QUEUE_LABELS[plan.next_queue]}."
    )
    console.print(summary, style="bold cyan")
    if plan.open_slots:
        console.print(
            f"No remaining artist fit the final {plan.open_slots} release "
            "slots; they remain open.",
            style="yellow",
        )


@app.command(name="plan-discographies")
def plan_discographies_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build the interactive plan without removing playlist markers.",
    ),
) -> None:
    """Choose the next round-week discographies and clear their queue markers."""
    console = Console()
    configuration = Settings()
    try:
        playlist_ids = discography.parse_playlist_ids(
            configuration.discography_newfoundland_playlist,
            configuration.discography_memory_lane_playlist,
            configuration.discography_requeue_playlist,
        )
        queue_3_playlist_id = discography.parse_playlist_id(
            configuration.the_queue_3_playlist,
            "THE_QUEUE_3_PLAYLIST",
        )
    except discography.DiscographyConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        console.print(line, style="cyan", markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    status_ref: Status | None = None
    try:
        with console.status("Planning the next discography batch") as status:
            status_ref = status
            plan = discography.build_discography_plan(
                review_client(),
                playlist_ids,
                lambda artist, candidates: ask_discography_release_selection(
                    console,
                    artist,
                    candidates,
                    status_ref,
                ),
                queue_3_playlist_id=queue_3_playlist_id,
                retry_call=retry_call,
                progress_callback=status.update,
            )
        _print_discography_plan(console, plan)
        if not plan.artists or dry_run:
            if dry_run and plan.artists:
                console.print(
                    "Dry run: playlists and queue-priority state were unchanged.",
                    style="bold cyan",
                )
            return

        action = Prompt.ask(
            "Remove these artists from the discography queues?",
            choices=["y", "n", "q"],
            default="n",
            console=console,
        )
        if action in {"n", "q"}:
            console.print("Nothing was changed.", style="yellow")
            return
        with console.status("Removing confirmed discography artists") as status:
            summary = discography.apply_discography_plan(
                review_client(),
                plan,
                retry_call=retry_call,
                progress_callback=status.update,
            )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except discography.DiscographyCancelledError as exc:
        console.print(str(exc), style="bold yellow", markup=False)
        raise typer.Exit(code=0) from exc
    except discography.DiscographyError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt as exc:
        console.print("Discography planning cancelled.", style="bold yellow")
        raise typer.Exit(code=0) from exc

    console.print(
        f"Removed {summary.removed_artists} artists "
        f"({summary.removed_markers} marker tracks). "
        f"The next run starts with {discography.QUEUE_LABELS[summary.next_queue]}.",
        style="bold green",
    )


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
            "Start the alphabetical selection at this 1-based position, Spotify "
            "album id/URI/URL, exact album title, or 'Artist - Album'."
        ),
    ),
    set_alphabetical_cursor: int | None = typer.Option(
        None,
        "--set-alphabetical-cursor",
        min=1,
        help=(
            "Persist this 1-based position as the next alphabetical album and "
            "exit without changing the playlist."
        ),
    ),
) -> None:
    """Add five alphabetical and five historical album first tracks."""
    console = Console()
    if set_alphabetical_cursor is not None and dry_run:
        raise typer.BadParameter(
            "--set-alphabetical-cursor persists immediately and cannot use --dry-run"
        )
    if set_alphabetical_cursor is not None and alphabetical_start is not None:
        raise typer.BadParameter(
            "use either --set-alphabetical-cursor or --alphabetical-start, not both"
        )

    def echo(line: str = "") -> None:
        style = "bold green" if line.startswith("Added") else "cyan"
        console.print(line, style=style, markup=False)

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None = None
    summary: palace_of_memory.PalaceOfMemorySummary | None = None
    try:
        if set_alphabetical_cursor is not None:
            with console.status("Setting the Palace alphabetical cursor") as status:
                cursor_update = palace_of_memory.set_alphabetical_cursor(
                    review_client(),
                    set_alphabetical_cursor,
                    progress_callback=status.update,
                    retry_call=retry_call,
                )
        else:
            configuration = Settings()
            playlist_id = palace_of_memory.parse_playlist_id(
                configuration.palace_of_memory_playlist
            )
            with console.status(
                "Planning Palace of Memory" + (" (dry run)" if dry_run else "")
            ) as status:
                summary = palace_of_memory.fill_palace_of_memory(
                    review_client(),
                    playlist_id,
                    dry_run=dry_run,
                    alphabetical_start=alphabetical_start,
                    echo=echo,
                    progress_callback=status.update,
                    retry_call=retry_call,
                )
    except review_album_limits.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except review_album_limits.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        raise typer.Exit(code=0) from exc
    except palace_of_memory.PalaceOfMemoryError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    if cursor_update is not None:
        refresh = cursor_update.album_refresh
    elif summary is not None:
        refresh = summary.album_refresh
    else:
        raise AssertionError("Palace command completed without a result")
    refresh_action = "updated" if refresh.persisted else "already current"
    console.print(
        f"Saved albums {refresh_action}: {refresh.previous} -> {refresh.current} "
        f"({refresh.added} added, {refresh.removed} removed, "
        f"{refresh.skipped} skipped).",
        style="bold cyan",
    )
    if refresh.backup_path:
        console.print(f"Album mirror backup: {refresh.backup_path}", style="dim")

    if cursor_update is not None:
        console.print(
            f"Alphabetical cursor set to {cursor_update.next_index + 1}: "
            f"{cursor_update.next_album.artist} - {cursor_update.next_album.album}. "
            "The playlist was not changed.",
            style="bold green",
        )
        return

    assert summary is not None

    table = Table(title="Palace of Memory")
    table.add_column("Source")
    table.add_column("Date / position")
    table.add_column("Artist")
    table.add_column("Album")
    table.add_column("First track")
    table.add_column("Action")
    action_styles = {
        "added": "bold green",
        "already present": "cyan",
        "duplicate selection": "yellow",
        "no match": "bold red",
    }
    for result in summary.results:
        if result.selected_date is None:
            location = "saved albums"
        else:
            location = (
                f"{result.selected_date.isoformat()} · "
                f"{result.history_position}/{result.albums_on_date}"
            )
        resolved_album = (
            result.spotify_album.album
            if result.spotify_album is not None
            else result.album
        )
        action = "would add" if dry_run and result.action == "added" else result.action
        table.add_row(
            result.source,
            location,
            result.artist,
            resolved_album,
            result.first_track.name if result.first_track is not None else "-",
            Text(action, style=action_styles[result.action]),
        )
    console.print(table)
    console.print(
        f"Random.org timestamp: "
        f"{summary.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')} · "
        f"cutoff {summary.cutoff_date.isoformat()} · "
        f"{summary.available_dates} eligible dates.",
        style="cyan",
    )
    console.print(
        "Alphabetical cursor"
        + (" (manual)" if summary.alphabetical_cursor_overridden else "")
        + f": {summary.alphabetical_start_index + 1} -> "
        f"{summary.alphabetical_next_index + 1}. Playlist: "
        f"{summary.playlist_length_before} -> {summary.playlist_length_after} tracks"
        + (" (preview only)." if dry_run else "."),
        style="bold cyan" if dry_run else "bold green",
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
) -> None:
    """Select past scrobbles and add their Spotify matches to the playlist."""
    console = Console()
    if count is not None and max_playlist_length is not None:
        raise typer.BadParameter(
            "use either --count or --max-playlist-length, not both"
        )

    configuration = Settings()
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            configuration.blast_from_the_past_playlist
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    effective_count = 10 if count is None and max_playlist_length is None else count
    status_text = "Preparing Last.fm scrobbles"
    try:
        with console.status(status_text) as status:
            summary = blast_from_past.add_blast_from_past_to_spotify(
                client(),
                playlist_id,
                count=effective_count,
                max_playlist_length=max_playlist_length,
                progress_callback=status.update,
            )
    except blast_from_past.BlastFromPastError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    if summary.batch is None:
        console.print(
            f"Playlist already contains {summary.playlist_length_before} items; "
            "nothing was added.",
            style="bold green",
        )
        return

    console.print(
        "Random.org timestamp: "
        f"{summary.batch.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        style="bold cyan",
    )
    console.print(
        f"Eligible dates: {summary.batch.available_dates} "
        f"({blast_from_past.FIRST_ELIGIBLE_DATE.isoformat()} through "
        f"{summary.batch.cutoff_date.isoformat()})",
        style="dim",
    )

    print_scrobble_selection_table(console, "A blast from the past", summary.results)
    console.print(
        f"Playlist: {summary.playlist_length_before} -> "
        f"{summary.playlist_length_after} items; added {summary.added} of "
        f"{summary.requested_count} selections.",
        style="bold",
    )


@app.command(name="daily-mind-radio")
def daily_mind_radio_command() -> None:
    """Add tracks from today's Last.fm anniversaries to Daily Mind Radio."""
    console = Console()
    configuration = Settings()
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            configuration.daily_mind_radio_playlist,
            setting_name="DAILY_MIND_RADIO_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    try:
        with console.status("Preparing anniversary scrobbles") as status:
            summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
                client(),
                playlist_id,
                progress_callback=status.update,
            )
    except blast_from_past.BlastFromPastError as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    target_dates = ", ".join(
        target_date.isoformat() for target_date in summary.batch.target_dates
    )
    console.print(f"Anniversary dates: {target_dates}", style="dim")
    if summary.batch.missing_dates:
        missing_dates = ", ".join(
            missing_date.isoformat() for missing_date in summary.batch.missing_dates
        )
        console.print(f"No scrobbles, skipped: {missing_dates}", style="yellow")

    if not summary.batch.selections:
        console.print(
            "None of today's anniversary dates had scrobbles; nothing was added.",
            style="bold green",
        )
        return

    generated_at = summary.batch.generated_at
    if generated_at is None:
        raise RuntimeError("A populated Daily Mind Radio batch has no timestamp.")
    console.print(
        f"Random.org timestamp: {generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        style="bold cyan",
    )
    print_scrobble_selection_table(console, "Daily mind radio", summary.results)
    console.print(
        f"Playlist: {summary.playlist_length_before} -> "
        f"{summary.playlist_length_after} items; added {summary.added} of "
        f"{len(summary.batch.selections)} populated anniversary dates.",
        style="bold",
    )


@app.command(name="genre-reveal")
def genre_reveal_command(
    state_path: Annotated[
        Path,
        typer.Option(
            "--state-path",
            help="Path to the shared Genre Reveal progress file.",
        ),
    ] = genre_reveal.DEFAULT_STATE_PATH,
    log_path: Annotated[
        Path,
        typer.Option(
            "--log-path",
            help="Path to the append-only Genre Reveal audit log.",
        ),
    ] = genre_reveal.DEFAULT_LOG_PATH,
    open_pages: bool = typer.Option(
        True,
        "--open-pages/--no-open-pages",
        help="Open the Every Noise and Spotify source pages after completion.",
    ),
) -> None:
    """Save and sample the first unchecked Every Noise genre playlist."""
    console = Console()
    configuration = Settings()
    try:
        destination_playlist_id = genre_reveal.parse_destination_playlist_id(
            configuration.genre_reveal_playlist
        )
        state = genre_reveal.load_genre_reveal_state(state_path)
        entry = genre_reveal.first_incomplete_genre(state)
    except (
        genre_reveal.GenreRevealConfigError,
        genre_reveal.GenreRevealStateError,
        genre_reveal.GenreRevealCompleteError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    try:
        with console.status(f"Processing {entry.name}"):
            result = genre_reveal.process_next_genre(
                client(),
                entry.slug,
                entry.name,
                destination_playlist_id,
                log_path=log_path,
            )
            genre_reveal.mark_genre_completed(entry.slug, state_path)
    except (
        genre_reveal.GenreRevealSourceError,
        genre_reveal.GenreRevealStateError,
        genre_reveal.GenreRevealLogError,
        blast_from_past.BlastFromPastError,
    ) as exc:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
            markup=False,
        )
        raise typer.Exit(code=1) from exc

    table = Table(title="Genre reveal")
    table.add_column("#", justify="right")
    table.add_column("Genre")
    table.add_column("Source playlist")
    table.add_column("Added", justify="right")
    table.add_column("Already present", justify="right")
    table.add_row(
        str(entry.position),
        entry.name,
        result.source_playlist_id,
        str(len(result.added_track_uris)),
        str(len(result.already_present_track_uris)),
    )
    console.print(table)
    console.print(f"Every Noise: {result.every_noise_url}", markup=False)
    console.print(f"Spotify: {result.source_playlist_url}", markup=False)
    console.print(
        f"Saved the source playlist and completed {entry.name}.",
        style="bold green",
    )

    if open_pages:
        typer.launch(result.every_noise_url)
        typer.launch(result.source_playlist_url)


@app.command(name="refresh-spotify-tokens")
def refresh_spotify_tokens() -> None:
    """Authenticate or force-refresh every configured Spotify app token."""
    spotify = review_client()
    if not isinstance(spotify, RotatingSpotify):
        raise typer.BadParameter("the configured client does not support app rotation")
    try:
        refreshed = spotify.refresh_all_app_tokens()
    except Exception as exc:
        typer.echo(f"Spotify token refresh failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Spotify tokens ready: {', '.join(refreshed)}")


def wait_for_library_retry(
    console: Console,
    notice: library_sync.RetryNotice,
    spotify: Spotify,
    progress: Progress | None = None,
) -> bool:
    """Wait for a retry while accepting rotate or quit without Enter."""
    if progress is not None:
        progress.stop()
    retry_at = datetime.now().astimezone() + timedelta(seconds=notice.delay_seconds)
    failure = (
        f"Spotify HTTP {notice.http_status}"
        if notice.http_status is not None
        else "Spotify connection interrupted"
    )
    console.print(
        f"{failure} while {notice.operation}.",
        style="bold yellow",
    )
    console.print(
        f"Retry {notice.attempt} at {retry_at.isoformat(timespec='seconds')}. "
        "Press r to rotate credentials and retry now, or q to save and quit.",
        style="yellow",
    )
    try:
        if not sys.stdin.isatty():
            sleep(notice.delay_seconds)
            return True

        descriptor = sys.stdin.fileno()
        old_settings = termios.tcgetattr(descriptor)
        deadline = monotonic() + notice.delay_seconds
        try:
            tty.setcbreak(descriptor)
            with Live(console=console, refresh_per_second=2, transient=True) as live:
                while True:
                    remaining = max(0, int(deadline - monotonic() + 0.999))
                    if remaining == 0:
                        return True
                    live.update(
                        Text(
                            f"Retrying in {remaining} seconds. "
                            "Press r to rotate or q to quit.",
                            style="yellow",
                        )
                    )
                    readable, _, _ = select.select(
                        [sys.stdin],
                        [],
                        [],
                        min(1.0, remaining),
                    )
                    if readable:
                        action = sys.stdin.read(1).lower()
                        if action == "q":
                            return False
                        if action == "r":
                            rotate = getattr(spotify, "rotate_credentials", None)
                            if not callable(rotate):
                                console.print(
                                    "This Spotify client cannot rotate credentials; "
                                    "continuing the retry wait.",
                                    style="bold yellow",
                                )
                                continue
                            try:
                                label = rotate()
                            except Exception as exc:
                                console.print(
                                    f"Could not rotate credentials: {exc} "
                                    "Continuing the retry wait.",
                                    style="bold yellow",
                                )
                                continue
                            console.print(
                                f"Rotated to {label}; retrying now.",
                                style="bold green",
                            )
                            return True
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, old_settings)
    finally:
        if progress is not None:
            progress.start()


def print_library_analysis_summary(
    console: Console,
    summary: library_sync.LibrarySyncSummary,
) -> None:
    """Render the common completion table for either analysis mode."""
    labels = {
        "albums": "Saved albums",
        "tracks": "Liked tracks",
        "artists": "Followed artists",
    }
    title = (
        "Export library mirror updated"
        if summary.mode == "async"
        else "Live library mirror updated"
    )
    table = Table(title=title)
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
            resource.source,
            str(resource.previous),
            str(resource.current),
            str(resource.added),
            str(resource.removed),
            str(resource.skipped),
        )
    console.print(table)
    console.print(f"Run: {summary.run_id}", style="bold")
    console.print(f"Undo backup: {summary.backup_dir}", style="dim")
    console.print(f"Audit manifest: {summary.backup_dir}/manifest.json", style="dim")


def run_library_analysis(mode: library_sync.AnalysisMode) -> None:
    """Run one analysis mode with shared Rich progress and error handling."""
    console = Console()
    labels = {
        "albums": "Saved albums",
        "tracks": "Liked tracks",
        "artists": "Followed artists",
    }
    progress_ref: Progress | None = None

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
                display_total = max(completed, total) if total is not None else None
                progress.update(
                    tasks[resource],
                    completed=completed,
                    total=display_total,
                    description=f"{labels[resource]}: {status}",
                )

            if mode == "async":
                summary = library_sync.analyse_library_async_routine(
                    echo=lambda line: console.print(
                        line,
                        style="yellow",
                        markup=False,
                    ),
                    progress_callback=update_progress,
                )
            else:
                spotify = review_client()
                summary = library_sync.analyse_library_sync_routine(
                    spotify,
                    echo=lambda line: console.print(
                        line,
                        style="yellow",
                        markup=False,
                    ),
                    progress_callback=update_progress,
                    retry_wait=lambda notice: wait_for_library_retry(
                        console,
                        notice,
                        spotify,
                        progress_ref,
                    ),
                )
    except library_sync.LibraryAnalysisCancelledError as exc:
        console.print(str(exc), style="bold yellow")
        console.print(
            "Progress was saved; rerun the same command to resume.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
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
    except KeyboardInterrupt as exc:
        console.print("Analysis paused. Progress was saved.", style="bold yellow")
        raise typer.Exit(code=0) from exc
    except library_sync.LibrarySyncError as exc:
        console.print(str(exc), style="bold red")
        console.print(
            "No partial staging data was published. Rerun to resume after fixing "
            "the underlying issue.",
            style="yellow",
        )
        raise typer.Exit(code=1) from exc

    print_library_analysis_summary(console, summary)


@app.command(name="analyse-library-async")
def analyse_library_async() -> None:
    """Build suffixed mirrors exclusively from YourLibrary.json."""
    run_library_analysis("async")


@app.command(name="analyse-library-sync")
def analyse_library_sync() -> None:
    """Build suffixed mirrors exclusively from the live Spotify API."""
    run_library_analysis("sync")


@app.command(name="restore-library-sync")
def restore_library_sync_command(
    run_id: str = typer.Argument(help="Completed library-analysis run id."),
    yes: bool = typer.Option(False, "--yes", help="Restore without prompting."),
) -> None:
    """Restore generated library files from an async or sync backup."""
    if not yes and not typer.confirm(
        f"Restore generated library files from analysis {run_id}?"
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
    name: str = typer.Argument(None, help="Exact Spotify artist name."),
    artist_id: str = typer.Option(None, "--artist-id", help="Spotify artist id."),
) -> None:
    """Show live liked-track and saved-release counts for an artist."""
    if not name and not artist_id:
        raise typer.BadParameter("provide an artist NAME or --artist-id")
    try:
        stats = get_live_artist_library_stats(
            client(),
            name=name,
            artist_id=artist_id,
        )
    except AmbiguousArtistError as exc:
        typer.echo(str(exc), err=True)
        for candidate in exc.candidates:
            typer.echo(
                f"  {candidate['artist']} ({candidate['id']})",
                err=True,
            )
        raise typer.Exit(code=1) from exc
    except (ArtistNotFoundError, SpotifyLookupResponseError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        typer.echo(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except RequestException as exc:
        typer.echo(
            "Spotify could not be reached after several attempts. "
            "Please try again shortly.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(stats.model_dump_json(indent=2))


@app.command()
def album_decision(
    name: str = typer.Argument(None, help="Exact Spotify album name."),
    album_id: str = typer.Option(None, "--album-id", help="Spotify album id."),
    artist: str = typer.Option(None, "--artist", help="Disambiguate by artist."),
    threshold: float = 0.5,
) -> None:
    """Evaluate an album against live Spotify Liked Songs state."""
    if not name and not album_id:
        raise typer.BadParameter("provide an album NAME or --album-id")
    try:
        evaluation = evaluate_album_live(
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
    except (AlbumNotFoundError, SpotifyLookupResponseError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        typer.echo(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except RequestException as exc:
        typer.echo(
            "Spotify could not be reached after several attempts. "
            "Please try again shortly.",
            err=True,
        )
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
            review_album_limits.format_transient_spotify_failure(exc) + ".",
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
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "Recovery progress was saved up to the last completed album.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc


@app.command(name="review-artists")
def review_artists_command(
    refresh_cache: bool = typer.Option(
        False,
        "--refresh-cache",
        help="Discard cached catalog candidates before reviewing.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Process at most this many pending artists.",
    ),
) -> None:
    """Review followed artists and place one track in the matching queue."""
    console = Console()
    progress_ref: Progress | None = None
    configuration = Settings()
    try:
        playlists = artist_review.QueuePlaylists.from_references(
            configuration.the_queue_playlist,
            configuration.the_queue_2_playlist,
            configuration.the_queue_3_playlist,
        )
    except artist_review.ArtistReviewConfigError as exc:
        console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc

    def echo(line: str = "") -> None:
        style = None
        if line.startswith("Auto-unfollowed"):
            style = "bold red"
        elif line.startswith("Planned automatic unfollow"):
            style = "yellow"
        elif line.startswith("Queued"):
            style = "bold green"
        elif line.startswith("Moved"):
            style = "bold cyan"
        elif line.startswith("Already queued") or line.startswith("Kept"):
            style = "green"
        elif line.startswith("Declined") or line.startswith("No eligible"):
            style = "dim yellow"
        elif line.startswith("No unliked"):
            style = "dim yellow"
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
            progress_ref = progress
            task_id = progress.add_task("Reviewing artists", total=None)

            def update_progress(position: int, total: int, artist_name: str) -> None:
                progress.update(
                    task_id,
                    completed=position,
                    total=total,
                    description=f"Reviewing artists: {artist_name}",
                )

            summary = artist_review.review_artists(
                review_client(),
                playlists,
                track_choice_reader=lambda artist, candidates: ask_artist_track_choice(
                    console,
                    artist,
                    candidates,
                    progress_ref,
                ),
                release_choice_reader=lambda artist, candidates, allow_decline: (
                    ask_artist_release_choice(
                        console,
                        artist,
                        candidates,
                        allow_decline,
                        progress_ref,
                    )
                ),
                echo=echo,
                progress_callback=update_progress,
                refresh_cache=refresh_cache,
                limit=limit,
            )
    except artist_review.SpotifyRateLimitError as exc:
        console.print(
            "Spotify rate limit reached. "
            f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}.",
            style="bold yellow",
        )
        console.print(
            "Artist review progress and pending automatic decisions were saved.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except artist_review.SpotifyTransientServerError as exc:
        console.print(
            review_album_limits.format_transient_spotify_failure(exc) + ".",
            style="bold yellow",
        )
        console.print(
            "Artist review progress and pending automatic decisions were saved.",
            style="yellow",
        )
        raise typer.Exit(code=0) from exc
    except artist_review.ArtistReviewError as exc:
        console.print(str(exc), style="bold red")
        raise typer.Exit(code=1) from exc
    except SpotifyException as exc:
        console.print(
            f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}",
            style="bold red",
        )
        raise typer.Exit(code=1) from exc

    table = Table(
        title="Artist review paused" if summary.paused else "Artist review complete"
    )
    table.add_column("Reviewed", justify="right")
    table.add_column("Unfollowed", justify="right", style="red")
    table.add_column("Queued", justify="right", style="green")
    table.add_column("Moved", justify="right", style="cyan")
    table.add_column("Already queued", justify="right")
    table.add_column("Declined", justify="right")
    table.add_column("No action", justify="right")
    table.add_column("Skipped", justify="right", style="yellow")
    table.add_row(
        str(summary.reviewed),
        str(summary.unfollowed),
        str(summary.queued),
        str(summary.moved),
        str(summary.already_queued),
        str(summary.declined),
        str(summary.no_action),
        str(summary.skipped),
    )
    console.print(table)


if __name__ == "__main__":
    """Main."""
    app()
    print("Done!")
