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
from spotify_manager.loaders_savers import load_total_albums_new_file
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.loaders_savers import save_total_albums_new_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors.library_lookups import evaluate_album


REMOVED_ALBUMS_LOG_PATH = (
    Path(__file__).resolve().parent.parent / "files" / "removed_albums_log.jsonl"
)

Echo = Callable[[str], None]
ActionReader = Callable[[YourLibraryAlbum, AlbumEvaluation], str]


@dataclass(frozen=True)
class AlbumArtist:
    """Spotify artist identity for a saved album."""

    spotify_id: str
    name: str


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


def format_album_label(album: YourLibraryAlbum) -> str:
    """Return a compact label for an album."""
    return f"{album.artist} - {album.album}"


def format_evaluation_summary(evaluation: AlbumEvaluation) -> str:
    """Return a compact liked-track summary for an evaluation."""
    liked_pct = evaluation.liked_ratio * 100
    threshold_pct = evaluation.threshold * 100
    return (
        f"Liked: {evaluation.liked_tracks} / {evaluation.total_tracks} "
        f"({liked_pct:.1f}%, threshold {threshold_pct:.1f}%)"
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


def append_removed_album_log(
    album: YourLibraryAlbum,
    evaluation: AlbumEvaluation,
    log_path: Path = REMOVED_ALBUMS_LOG_PATH,
) -> None:
    """Append one removed-album event as JSON Lines."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "removed_at": datetime.now(UTC).isoformat(),
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
    with open(log_path, "a") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


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

    checked_artist_ids.add(artist.spotify_id)
    echo(f"Followed artist: {artist.name}")
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
        if action in {"r", "remove"}:
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
) -> None:
    """Review saved albums and remove user-approved albums below the threshold."""
    total_albums = load_total_albums_new_file()
    library = load_your_library_file()
    remaining_albums = list(total_albums)
    total_count = len(total_albums)

    removed_count = 0
    skipped_count = 0
    kept_count = 0
    followed_artist_count = 0
    known_artist_ids = known_artist_ids_by_name(library)
    checked_artist_ids: set[str] = set()

    for position, album in enumerate(total_albums, start=1):
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

        label = format_album_label(album)
        summary = format_evaluation_summary(evaluation)

        if evaluation.decision == "keep":
            kept_count += 1
            echo(f"[{position}/{total_count}] keep: {label} - {summary}")
            continue

        echo("")
        echo(f"[{position}/{total_count}] remove candidate: {label}")
        echo(summary)
        echo(f"Source: {evaluation.source}")

        action = read_action(album, evaluation, action_reader, echo)
        if action == "quit":
            echo("Stopping review.")
            break
        if action in {"keep", "skip"}:
            skipped_count += 1
            echo(f"Skipped: {label}")
            continue

        try:
            sp.current_user_saved_albums_delete([album.spotify_id])
        except SpotifyException as exc:
            handle_spotify_exception(exc)

        remaining_albums = remove_first_matching_album(
            remaining_albums, album.spotify_id
        )
        save_total_albums_new_file(remaining_albums)
        append_removed_album_log(album, evaluation, log_path=log_path)
        removed_count += 1
        echo(f"Removed: {label}")

    echo("")
    echo(
        "Review complete. "
        f"Kept: {kept_count}. Skipped: {skipped_count}. "
        f"Removed: {removed_count}. Followed artists: {followed_artist_count}."
    )
