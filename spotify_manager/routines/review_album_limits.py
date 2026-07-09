"""Interactive routine for removing albums below the liked-track threshold."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from math import ceil
from pathlib import Path

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.loaders_savers import load_stats_history_file
from spotify_manager.loaders_savers import load_total_albums_new_file
from spotify_manager.loaders_savers import load_total_artists_file
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.loaders_savers import save_stats_history
from spotify_manager.loaders_savers import save_total_albums_new_file
from spotify_manager.loaders_savers import save_total_artists_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.utils.growth import calculate_growth
from spotify_manager.utils.sorting import artist_sort_key


REMOVED_ALBUMS_LOG_PATH = (
    Path(__file__).resolve().parent.parent / "files" / "removed_albums_log.jsonl"
)
REVIEW_DECISIONS_PATH = (
    Path(__file__).resolve().parent.parent
    / "files"
    / "review_album_limits_decisions.json"
)
TRACK_CONTAINS_BATCH_SIZE = 20

Echo = Callable[[str], None]
ActionReader = Callable[[YourLibraryAlbum, AlbumEvaluation], str]
ProgressCallback = Callable[[int, int], None]
ReviewDecisions = dict[str, dict[str, object]]


@dataclass(frozen=True)
class AlbumArtist:
    """Spotify artist identity for a saved album."""

    spotify_id: str
    name: str


@dataclass(frozen=True)
class ArtistPersistenceResult:
    """Local file update result after following an artist."""

    total_artists_updated: bool
    stats_history_updated: bool


class SpotifyRateLimitError(RuntimeError):
    """Raised when Spotify asks the client to retry later."""

    def __init__(self, retry_after_seconds: int | None) -> None:
        """Store the retry delay reported by Spotify, when present."""
        super().__init__("Spotify rate limit reached")
        self.retry_after_seconds = retry_after_seconds


def get_retry_after_seconds(exc: SpotifyException) -> int | None:
    """Return Spotify's retry-after delay when ``exc`` is a rate limit."""
    if exc.http_status != 429:
        return None

    retry_after = exc.headers.get("Retry-After") or exc.headers.get("retry-after")
    if retry_after is None:
        return None

    try:
        return max(0, int(float(retry_after)))
    except ValueError:
        return None


def format_retry_after(retry_after_seconds: int | None) -> str:
    """Format a retry-after value for CLI output."""
    if retry_after_seconds is None:
        return "try again later"

    minutes = max(1, ceil(retry_after_seconds / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return f"try again in {minutes} {unit}"


def current_stats_history_key(now: datetime | None = None) -> str:
    """Return the date key used by stats_history.json."""
    current_time = now or datetime.now()
    month = (
        str(current_time.month)
        if current_time.month >= 10
        else f"0{current_time.month}"
    )
    return f"{current_time.year}.{month}.{current_time.day}"


def handle_spotify_exception(exc: SpotifyException) -> None:
    """Raise a clean rate-limit exception, or re-raise the original error."""
    retry_after_seconds = get_retry_after_seconds(exc)
    if exc.http_status == 429:
        raise SpotifyRateLimitError(retry_after_seconds) from exc
    raise exc


def normalise_name(value: str) -> str:
    """Normalise a name for case-insensitive artist lookups."""
    return value.strip().casefold()


def known_artist_ids_by_name(library: YourLibraryFile) -> dict[str, str]:
    """Return followed artist ids from the exported library, keyed by name."""
    return {
        normalise_name(artist.name): artist.spotify_id for artist in library.artists
    }


def resolve_album_artist(
    sp: Spotify,
    album: YourLibraryAlbum,
    known_artist_ids: dict[str, str],
) -> AlbumArtist | None:
    """Resolve the Spotify artist id for an album from local data or Spotify."""
    known_artist_id = known_artist_ids.get(normalise_name(album.artist))
    if known_artist_id:
        return AlbumArtist(spotify_id=known_artist_id, name=album.artist)

    try:
        spotify_album = sp.album(album.spotify_id)
    except SpotifyException as exc:
        handle_spotify_exception(exc)

    spotify_artists = spotify_album.get("artists", [])
    if not spotify_artists:
        return None

    artist = next(
        (
            candidate
            for candidate in spotify_artists
            if normalise_name(candidate.get("name", "")) == normalise_name(album.artist)
        ),
        spotify_artists[0],
    )
    artist_id = artist.get("id")
    if not artist_id:
        return None

    artist_name = artist.get("name") or album.artist
    known_artist_ids[normalise_name(album.artist)] = artist_id
    known_artist_ids[normalise_name(artist_name)] = artist_id
    return AlbumArtist(spotify_id=artist_id, name=artist_name)


def to_library_artist(artist: AlbumArtist) -> YourLibraryArtist:
    """Convert a followed album artist to the local artist file model."""
    return YourLibraryArtist(
        name=artist.name,
        uri=f"spotify:artist:{artist.spotify_id}",
    )


def add_followed_artist_to_total_file(artist: AlbumArtist) -> bool:
    """Add a newly followed artist to artists_total.json when absent."""
    total_artists = load_total_artists_file()
    if any(
        stored_artist.spotify_id == artist.spotify_id for stored_artist in total_artists
    ):
        return False

    updated_artists = [*total_artists, to_library_artist(artist)]
    save_total_artists_file(sorted(updated_artists, key=artist_sort_key))
    return True


def report_with_followed_artist(
    report: StatsReport,
    existing_period: bool,
) -> StatsReport:
    """Return ``report`` with one newly followed artist counted."""
    current_artist_stats = report.artists_stats
    total_followed_artists = current_artist_stats.total_followed_artists + 1
    removed_artists = current_artist_stats.removed_artists if existing_period else 0
    added_artists = current_artist_stats.added_artists + 1 if existing_period else 1
    previous_total_followed_artists = (
        current_artist_stats.total_followed_artists
        - current_artist_stats.added_artists
        + current_artist_stats.removed_artists
        if existing_period
        else current_artist_stats.total_followed_artists
    )

    updated_artists_stats = current_artist_stats.model_copy(
        update={
            "total_followed_artists": total_followed_artists,
            "removed_artists": removed_artists,
            "added_artists": added_artists,
            "growth": calculate_growth(
                total_followed_artists,
                previous_total_followed_artists,
            ),
        }
    )

    return report.model_copy(
        update={
            "artists_stats": updated_artists_stats,
            "avg_albums_per_artists": (
                report.albums_stats.total_saved_albums // total_followed_artists
            ),
            "avg_liked_tracks_per_artists": (
                report.tracks_stats.total_liked_tracks // total_followed_artists
            ),
        }
    )


def update_stats_history_for_followed_artist() -> bool:
    """Record one newly followed artist in stats_history.json."""
    stats_history = load_stats_history_file()
    if not stats_history:
        return False

    key = current_stats_history_key()
    existing_period = key in stats_history
    source_report = (
        stats_history[key]
        if existing_period
        else next(reversed(stats_history.values()))
    )
    stats_history[key] = report_with_followed_artist(source_report, existing_period)
    save_stats_history(stats_history)
    return True


def record_followed_artist(artist: AlbumArtist) -> ArtistPersistenceResult:
    """Persist a newly followed artist to local files."""
    total_artists_updated = add_followed_artist_to_total_file(artist)
    if not total_artists_updated:
        return ArtistPersistenceResult(
            total_artists_updated=False,
            stats_history_updated=False,
        )

    return ArtistPersistenceResult(
        total_artists_updated=True,
        stats_history_updated=update_stats_history_for_followed_artist(),
    )


def format_album_label(album: YourLibraryAlbum) -> str:
    """Return a compact label for an album."""
    return f"{album.album} - {album.artist}"


def format_evaluation_summary(evaluation: AlbumEvaluation) -> str:
    """Return a compact liked-track summary for an evaluation."""
    liked_pct = evaluation.liked_ratio * 100
    threshold_pct = evaluation.threshold * 100
    return (
        f"Liked: {evaluation.liked_tracks} / {evaluation.total_tracks} "
        f"({liked_pct:.1f}%, threshold {threshold_pct:.1f}%, "
        f"required {evaluation.required_liked_tracks})"
    )


def echo_track_details(evaluation: AlbumEvaluation, echo: Echo) -> None:
    """Print the liked/unliked track list for an album evaluation."""
    for index, track in enumerate(evaluation.tracks, start=1):
        marker = "liked" if track.liked else "not liked"
        echo(f"  {index:02d}. [{marker}] {track.name}")


def remove_first_matching_album(
    albums: list[YourLibraryAlbum], album_id: str
) -> list[YourLibraryAlbum]:
    """Return ``albums`` with the first matching Spotify album id removed."""
    remaining = list(albums)
    for index, album in enumerate(remaining):
        if album.spotify_id == album_id:
            del remaining[index]
            break
    return remaining


def load_review_decisions(
    decisions_path: Path = REVIEW_DECISIONS_PATH,
) -> ReviewDecisions:
    """Load persisted review decisions keyed by Spotify album id."""
    if not decisions_path.exists():
        return {}

    with open(decisions_path) as decisions_file:
        data = json.load(decisions_file)

    if not isinstance(data, dict):
        return {}

    return {
        str(album_id): entry
        for album_id, entry in data.items()
        if isinstance(entry, dict)
    }


def save_review_decisions(
    decisions: ReviewDecisions,
    decisions_path: Path = REVIEW_DECISIONS_PATH,
) -> None:
    """Persist review decisions atomically enough for CLI interruptions."""
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = decisions_path.with_suffix(f"{decisions_path.suffix}.tmp")
    with open(temporary_path, "w") as decisions_file:
        json.dump(decisions, decisions_file, ensure_ascii=False, indent=2)
        decisions_file.write("\n")
    temporary_path.replace(decisions_path)


def record_review_decision(
    decisions: ReviewDecisions,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    decision: str,
    decisions_path: Path = REVIEW_DECISIONS_PATH,
    live_liked_tracks: int | None = None,
) -> None:
    """Persist a user review decision for restart-safe reviews."""
    entry = {
        "decided_at": datetime.now(UTC).isoformat(),
        "decision": decision,
        "spotify_id": album.spotify_id,
        "album": album.album,
        "artist": album.artist,
        "liked_tracks": evaluation.liked_tracks,
        "total_tracks": evaluation.total_tracks,
        "liked_ratio": evaluation.liked_ratio,
        "threshold": evaluation.threshold,
        "from_cache": evaluation.from_cache,
        "source": evaluation.source,
    }
    if live_liked_tracks is not None:
        entry["live_liked_tracks"] = live_liked_tracks
    decisions[album.spotify_id] = entry
    save_review_decisions(decisions, decisions_path)


def has_persisted_keep_decision(
    album: YourLibraryAlbum,
    decisions: ReviewDecisions,
) -> bool:
    """Return whether this album was explicitly kept in a previous run."""
    return decisions.get(album.spotify_id, {}).get("decision") == "keep"


def append_removed_album_log(
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    action: str = "manual",
    live_liked_tracks: int | None = None,
) -> None:
    """Append one removed-album event as JSON Lines."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "removed_at": datetime.now(UTC).isoformat(),
        "action": action,
        "spotify_id": album.spotify_id,
        "album": album.album,
        "artist": album.artist,
        "liked_tracks": evaluation.liked_tracks,
        "total_tracks": evaluation.total_tracks,
        "liked_ratio": evaluation.liked_ratio,
        "threshold": evaluation.threshold,
        "from_cache": evaluation.from_cache,
        "source": evaluation.source,
    }
    if live_liked_tracks is not None:
        entry["live_liked_tracks"] = live_liked_tracks
    with open(log_path, "a") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def track_ids_from_evaluation(evaluation: AlbumEvaluation) -> list[str]:
    """Return Spotify track ids known for an album evaluation."""
    return [track.spotify_id for track in evaluation.tracks if track.spotify_id]


def get_live_liked_track_count(sp: Spotify, track_ids: list[str]) -> int:
    """Count album tracks currently saved by the user in Spotify."""
    liked_count = 0
    for start in range(0, len(track_ids), TRACK_CONTAINS_BATCH_SIZE):
        batch = track_ids[start : start + TRACK_CONTAINS_BATCH_SIZE]
        try:
            saved_statuses = sp.current_user_saved_tracks_contains(batch)
        except SpotifyException as exc:
            handle_spotify_exception(exc)
        liked_count += sum(1 for is_saved in saved_statuses if is_saved)
    return liked_count


def remove_album_from_library(
    sp: Spotify,
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    remaining_albums: list[YourLibraryAlbum],
    log_path: Path,
    action: str = "manual",
    live_liked_tracks: int | None = None,
) -> list[YourLibraryAlbum]:
    """Remove an album from Spotify and persist the local removal immediately."""
    try:
        sp.current_user_saved_albums_delete([album.spotify_id])
    except SpotifyException as exc:
        handle_spotify_exception(exc)

    updated_albums = remove_first_matching_album(remaining_albums, album.spotify_id)
    save_total_albums_new_file(updated_albums)
    append_removed_album_log(
        album,
        evaluation,
        log_path=log_path,
        action=action,
        live_liked_tracks=live_liked_tracks,
    )
    return updated_albums


def ensure_artist_followed(
    sp: Spotify,
    album: YourLibraryAlbum,
    known_artist_ids: dict[str, str],
    checked_artist_ids: set[str],
    echo: Echo,
) -> bool:
    """Follow an album's artist when not already followed.

    Returns ``True`` when a follow action was performed. Artist ids already
    checked in this run are skipped to avoid repeated API calls for artists with
    many albums.
    """
    artist = resolve_album_artist(sp, album, known_artist_ids)
    if artist is None:
        echo(f"Could not resolve artist id for: {album.artist}")
        return False

    if artist.spotify_id in checked_artist_ids:
        return False

    try:
        followed_response = sp.current_user_following_artists([artist.spotify_id])
    except SpotifyException as exc:
        handle_spotify_exception(exc)

    already_following = bool(followed_response[0]) if followed_response else False
    if already_following:
        checked_artist_ids.add(artist.spotify_id)
        return False

    try:
        sp.user_follow_artists([artist.spotify_id])
    except SpotifyException as exc:
        handle_spotify_exception(exc)

    persistence_result = record_followed_artist(artist)
    checked_artist_ids.add(artist.spotify_id)
    echo(f"Followed artist: {artist.name}")
    if persistence_result.total_artists_updated:
        echo(f"Recorded artist in artists_total.json: {artist.name}")
    if persistence_result.stats_history_updated:
        echo("Updated stats_history.json.")
    return True


def read_action(
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    action_reader: ActionReader,
    echo: Echo,
) -> str:
    """Read an action from the user, showing details when requested."""
    while True:
        action = action_reader(album, evaluation).strip().casefold()
        if action in {"r", "remove"} or (
            not action and evaluation.decision == "remove"
        ):
            return "remove"
        if action in {"k", "keep"}:
            return "keep"
        if action in {"s", "skip", ""}:
            return "skip"
        if action in {"q", "quit"}:
            return "quit"
        if action in {"d", "details"}:
            echo_track_details(evaluation, echo)
            continue
        echo("Choose r/remove, k/keep, s/skip, d/details, or q/quit.")


def review_album_limits(
    sp: Spotify,
    action_reader: ActionReader,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
    echo: Echo = print,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
    decisions_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Review saved albums and remove user-approved albums below the threshold."""
    decisions_path = decisions_path or REVIEW_DECISIONS_PATH
    total_albums = load_total_albums_new_file()
    library = load_your_library_file()
    remaining_albums = list(total_albums)
    review_decisions = load_review_decisions(decisions_path)
    total_count = len(total_albums)

    removed_count = 0
    skipped_count = 0
    kept_count = 0
    followed_artist_count = 0
    known_artist_ids = known_artist_ids_by_name(library)
    checked_artist_ids: set[str] = set()

    for position, album in enumerate(total_albums, start=1):
        label = format_album_label(album)
        if has_persisted_keep_decision(album, review_decisions):
            kept_count += 1
            echo(f"[{position}/{total_count}] previously kept: {label}")
            if progress_callback is not None:
                progress_callback(position, total_count)
            continue

        followed_artist = ensure_artist_followed(
            sp, album, known_artist_ids, checked_artist_ids, echo
        )
        if followed_artist:
            followed_artist_count += 1

        try:
            evaluation = evaluate_album(
                sp=sp,
                album_id=album.spotify_id,
                library=library,
                threshold=threshold,
                use_cache=use_cache,
                refresh_cache=refresh_cache,
            )
        except SpotifyException as exc:
            handle_spotify_exception(exc)

        summary = format_evaluation_summary(evaluation)

        if evaluation.decision == "keep":
            kept_count += 1
            echo(f"[{position}/{total_count}] keep: {label} - {summary}")
            if progress_callback is not None:
                progress_callback(position, total_count)
            continue

        echo("")
        echo(f"[{position}/{total_count}] remove candidate: {label}")
        echo(summary)
        echo(f"Source: {evaluation.source}")

        live_liked_tracks = None
        track_ids = track_ids_from_evaluation(evaluation)
        if track_ids:
            live_liked_tracks = get_live_liked_track_count(sp, track_ids)
            if live_liked_tracks == 0:
                remaining_albums = remove_album_from_library(
                    sp,
                    album,
                    evaluation,
                    remaining_albums,
                    log_path,
                    action="auto_zero_live_likes",
                    live_liked_tracks=live_liked_tracks,
                )
                removed_count += 1
                echo(f"Auto-removed (0 live liked tracks): {label}")
                if progress_callback is not None:
                    progress_callback(position, total_count)
                continue
            echo(f"Live liked tracks: {live_liked_tracks}")
        else:
            echo("Live liked tracks: unavailable; asking for confirmation.")

        action = read_action(album, evaluation, action_reader, echo)
        if action == "quit":
            echo("Stopping review.")
            break
        if action == "keep":
            record_review_decision(
                review_decisions,
                album,
                evaluation,
                "keep",
                decisions_path,
                live_liked_tracks=live_liked_tracks,
            )
            kept_count += 1
            echo(f"Kept anyway: {label}")
            if progress_callback is not None:
                progress_callback(position, total_count)
            continue
        if action == "skip":
            skipped_count += 1
            echo(f"Skipped: {label}")
            if progress_callback is not None:
                progress_callback(position, total_count)
            continue

        remaining_albums = remove_album_from_library(
            sp,
            album,
            evaluation,
            remaining_albums,
            log_path,
            live_liked_tracks=live_liked_tracks,
        )
        removed_count += 1
        echo(f"Removed: {label}")
        if progress_callback is not None:
            progress_callback(position, total_count)

    echo("")
    echo(
        "Review complete. "
        f"Kept: {kept_count}. Skipped: {skipped_count}. "
        f"Removed: {removed_count}. Followed artists: {followed_artist_count}."
    )
