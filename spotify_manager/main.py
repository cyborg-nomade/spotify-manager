"""Interface file."""

import select
import sys
import termios
import tty
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from time import monotonic
from time import sleep
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.prompt import Prompt
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
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.processors.library_lookups import get_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_sync
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio
from spotify_manager.routines import found_art
from spotify_manager.routines import genre_reveal
from spotify_manager.routines import recover_removed_albums
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import review_artists as artist_review
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
    console.print(
        f"Spotify HTTP {notice.http_status} while {notice.operation}.",
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
            "Spotify API temporarily unavailable "
            f"({exc.http_status}) after {exc.attempts} attempts "
            f"while {exc.operation}.",
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
