"""Progress and Spotify actions for the Every Noise genre-reveal route."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from pydantic import ValidationError
from spotipy import Spotify

from spotify_manager.application.genre_values import (
    GenreRevealCompleteError as GenreRevealCompleteError,
)
from spotify_manager.application.genre_values import (
    GenreRevealConfigError as GenreRevealConfigError,
)
from spotify_manager.application.genre_values import (
    GenreRevealLogError as GenreRevealLogError,
)
from spotify_manager.application.genre_values import (
    GenreRevealSourceError as GenreRevealSourceError,
)
from spotify_manager.application.genre_values import (
    GenreRevealStateError as GenreRevealStateError,
)

# UFI
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.compat import routine_state
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.genres import GenrePlaylistSource
from spotify_manager.domain.genres import GenreRouteEntry as GenreRouteEntry
from spotify_manager.infrastructure.genre_models import (
    GenreRevealRunRequest as GenreRevealRunRequest,
)
from spotify_manager.infrastructure.genre_models import (
    GenreRevealRunResult as GenreRevealRunResult,
)
from spotify_manager.infrastructure.genre_models import (
    GenreRevealSourcePreview as GenreRevealSourcePreview,
)
from spotify_manager.infrastructure.genre_models import (
    GenreRevealState as GenreRevealState,
)
from spotify_manager.infrastructure.genre_models import (
    GenreRevealStateUpdate as GenreRevealStateUpdate,
)
from spotify_manager.infrastructure.genre_sources import (
    EveryNoisePlaylistParser as _EveryNoisePlaylistParser,
)
from spotify_manager.routines import blast_from_past


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DEFAULT_STATE_PATH = FILES_DIR / "genre_reveal_state.json"
DEFAULT_LOG_PATH = FILES_DIR / "genre_reveal_log.jsonl"
DEFAULT_ROUTE_PATH = FRONTEND_DIR / "genre-reveal.html"
MAX_GENRES = 6_132
MAX_SLUG_LENGTH = 256
MAX_GENRE_NAME_LENGTH = 256
MAX_STATE_BACKUPS = 100
SOURCE_TRACK_COUNT = 10
EVERY_NOISE_URL_TEMPLATE = "https://everynoise.com/engenremap-{slug}.html"
SPOTIFY_EMBED_URL_TEMPLATE = "https://open.spotify.com/embed/playlist/{playlist_id}"
HTTP_USER_AGENT = "spotify-manager/0.1.0"
HTTP_TIMEOUT_SECONDS = 30
SPOTIFY_PLAYLIST_URL_PATTERN = re.compile(
    r"^https://open\.spotify\.com/(?:user/[^/]+/)?playlist/"
    r"(?P<id>[A-Za-z0-9]+)(?:[/?#].*)?$"
)
SPOTIFY_TRACK_URI_PATTERN = re.compile(r"spotify:track:[A-Za-z0-9]{22}")
GENRE_ROUTE_PATTERN = re.compile(
    r"const genres = (?P<route>\[\[.*?\]\]);\s+const STORAGE_KEY",
    re.DOTALL,
)
PageReader = Callable[[str], str]


@dataclass(frozen=True)
class _GenrePlaylistSource:
    """Resolved source playlist and its ordered first tracks."""

    preview: GenreRevealSourcePreview
    track_uris: tuple[str, ...]


def _validate_completed_slugs(slugs: list[str]) -> list[str]:
    from spotify_manager.infrastructure.genre_models import _validate_completed_slugs

    return _validate_completed_slugs(slugs)


def _default_state() -> dict[str, object]:
    """Return empty serialized Genre Reveal progress."""
    return GenreRevealState().model_dump(mode="json")


def validate_state(raw: object) -> dict[str, object]:
    """Validate Genre Reveal progress independently of storage.

    Args:
        raw: Original untrusted progress payload.

    Returns:
        Original normalized JSON-compatible progress.

    Raises:
        GenreRevealStateError: Original Pydantic validation fails.
    """
    try:
        return GenreRevealState.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        raise GenreRevealStateError("Genre-reveal state is invalid.") from exc


def _load_state_dict(path: Path) -> dict[str, object]:
    """Load serialized progress from one legacy file."""
    if not path.exists():
        return _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not read genre-reveal state from {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise GenreRevealStateError(f"Genre-reveal state is invalid: {path}") from exc
    return validate_state(raw)


def _state_access(
    path: Path,
    state_service: StateService | None,
) -> RoutineState:
    """Resolve shared production state or an explicit legacy test path."""
    return routine_state(
        name="genre_reveal",
        default_factory=_default_state,
        validator=validate_state,
        legacy_path=path,
        default_legacy_path=DEFAULT_STATE_PATH,
        legacy_loader=_load_state_dict,
        legacy_saver=_save_state_dict,
        service=state_service,
    )


def load_genre_reveal_state(
    path: Path = DEFAULT_STATE_PATH,
    *,
    state_service: StateService | None = None,
) -> GenreRevealState:
    """Load persisted progress, returning a new empty state when absent.

    Args:
        path: Original legacy state location.
        state_service: Optional original shared state service.

    Returns:
        Validated original progress and server metadata.

    Raises:
        GenreRevealStateError: Original state cannot be loaded or validated.
    """
    return GenreRevealState.model_validate(_state_access(path, state_service).load())


def _backup_name(path: Path) -> str:
    return path.name


def _backup_genre_reveal_state(path: Path, contents: str) -> None:
    """Preserve the current state before replacing it."""
    backup_directory = path.with_name(f"{path.stem}_backups")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = backup_directory / f"{path.stem}-{timestamp}.json"
    try:
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(contents, encoding="utf-8")
        backups = sorted(
            backup_directory.glob(f"{path.stem}-*.json"),
            key=_backup_name,
        )
        for stale_backup in backups[:-MAX_STATE_BACKUPS]:
            stale_backup.unlink()
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not back up genre-reveal state from {path}: {exc}"
        ) from exc


def _save_state_dict(state: dict[str, object], path: Path) -> None:
    """Back up and atomically replace one legacy state file."""
    normalized = validate_state(state)
    existing_contents: str | None = None
    if path.exists():
        try:
            existing_contents = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GenreRevealStateError(
                f"Could not read genre-reveal state from {path}: {exc}"
            ) from exc
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if existing_contents is not None:
            _backup_genre_reveal_state(path, existing_contents)
        temporary_path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not write genre-reveal state to {path}: {exc}"
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _persist_update(
    state_access: RoutineState,
    update: GenreRevealStateUpdate,
) -> GenreRevealState:
    """Replace user-editable progress while preserving server metadata."""
    from spotify_manager.bootstrap.genre_progress import update_genre_progress

    return update_genre_progress(state_access, update)


def save_genre_reveal_state(
    update: GenreRevealStateUpdate,
    path: Path = DEFAULT_STATE_PATH,
    *,
    state_service: StateService | None = None,
) -> GenreRevealState:
    """Replace persisted progress through the shared state interface.

    Args:
        update: Original validated editable progress.
        path: Original legacy state location.
        state_service: Optional original shared state service.

    Returns:
        Original current or accepted timestamped progress.

    Raises:
        GenreRevealStateError: Original state cannot be loaded or saved.
    """
    return _persist_update(_state_access(path, state_service), update)


def load_genre_route(
    path: Path = DEFAULT_ROUTE_PATH,
) -> tuple[GenreRouteEntry, ...]:
    """Load the preserved ordered route from its standalone HTML asset.

    Args:
        path: Original route asset location.

    Returns:
        Validated route entries in original order.

    Raises:
        GenreRevealStateError: Original asset cannot be read or decoded.
    """
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not read genre route from {path}: {exc}"
        ) from exc

    from spotify_manager.infrastructure.genre_sources import decode_route

    return decode_route(html, path, GENRE_ROUTE_PATTERN, MAX_GENRES)


def first_incomplete_genre(
    state: GenreRevealState,
    route_path: Path = DEFAULT_ROUTE_PATH,
) -> GenreRouteEntry:
    """Return the first route entry not present in persisted progress.

    Args:
        state: Original validated completed identities.
        route_path: Original route asset location.

    Returns:
        First unfinished entry in the original route order.

    Raises:
        GenreRevealStateError: Original route cannot be loaded.
        GenreRevealCompleteError: Every original route entry is complete.
    """
    from spotify_manager.domain.genres import first_incomplete

    completed = set(state.completed)
    entry = first_incomplete(load_genre_route(route_path), completed)
    if entry is None:
        raise GenreRevealCompleteError("Every genre in the route is complete.")
    return entry


def mark_genre_completed(
    slug: str,
    path: Path = DEFAULT_STATE_PATH,
    *,
    state_service: StateService | None = None,
) -> GenreRevealState:
    """Add one slug to the latest persisted state without changing its settings.

    Args:
        slug: Original genre identity to record as complete.
        path: Original legacy state location.
        state_service: Optional original shared state service.

    Returns:
        Original current or accepted updated progress.

    Raises:
        GenreRevealStateError: Original state cannot be read or written.
        ValidationError: A completed identity violates original boundary rules.
    """
    state_access = _state_access(path, state_service)
    state = GenreRevealState.model_validate(state_access.load())
    if slug not in state.completed:
        state.completed.append(slug)
    return _persist_update(
        state_access,
        GenreRevealStateUpdate(
            completed=state.completed,
            hide_done=state.hide_done,
        ),
    )


def read_public_page(url: str) -> str:
    """Fetch one public HTML page with a bounded timeout.

    Args:
        url: Original public source or embed URL.

    Returns:
        Original UTF-8 response text.

    Raises:
        GenreRevealSourceError: HTTP, reachability or UTF-8 decoding fails.
    """
    request = Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read().decode("utf-8")
    except HTTPError as exc:
        raise GenreRevealSourceError(
            f"Public page returned HTTP {exc.code}: {url}"
        ) from exc
    except URLError as exc:
        raise GenreRevealSourceError(
            f"Could not reach public page {url}: {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise GenreRevealSourceError(f"Public page was not valid UTF-8: {url}") from exc


def _playlist_id_from_url(url: str) -> str:
    """Extract a Spotify playlist id from a validated public URL."""
    match = SPOTIFY_PLAYLIST_URL_PATTERN.fullmatch(url)
    if match is None:
        raise GenreRevealSourceError(
            f"Every Noise returned an invalid Spotify playlist URL: {url}"
        )
    return match.group("id")


def discover_genre_source(
    slug: str,
    name: str,
    page_reader: PageReader = read_public_page,
) -> GenreRevealSourcePreview:
    """Find the primary Spotify playlist linked by an Every Noise genre page.

    Args:
        slug: Original genre identity.
        name: Original genre display name.
        page_reader: Original public-page reader.

    Returns:
        Original validated public source links.

    Raises:
        ValidationError: Original request values are invalid.
        GenreRevealSourceError: Original page or primary link is unavailable.
    """
    request = GenreRevealRunRequest(slug=slug, name=name)
    every_noise_url = EVERY_NOISE_URL_TEMPLATE.format(slug=request.slug)
    parser = _EveryNoisePlaylistParser()
    parser.feed(page_reader(every_noise_url))

    from spotify_manager.infrastructure.genre_sources import primary_playlist

    primary_url = primary_playlist(parser.links, request.name)

    playlist_id = _playlist_id_from_url(primary_url)
    return GenreRevealSourcePreview(
        slug=request.slug,
        name=request.name,
        every_noise_url=every_noise_url,
        source_playlist_id=playlist_id,
        source_playlist_uri=f"spotify:playlist:{playlist_id}",
        source_playlist_url=f"https://open.spotify.com/playlist/{playlist_id}",
    )


def _first_track_uris(embed_html: str) -> tuple[str, ...]:
    """Return the first distinct track URIs in Spotify's public embed order."""
    from spotify_manager.infrastructure.genre_sources import first_track_uris

    return first_track_uris(embed_html, SPOTIFY_TRACK_URI_PATTERN, SOURCE_TRACK_COUNT)


def load_genre_playlist_source(
    slug: str,
    name: str,
    page_reader: PageReader = read_public_page,
) -> _GenrePlaylistSource:
    """Resolve a genre's source playlist and its first ten ordered tracks.

    Args:
        slug: Original genre identity.
        name: Original genre display name.
        page_reader: Original public-page reader.

    Returns:
        Original public source and ordered distinct markers.

    Raises:
        ValidationError: Original request values are invalid.
        GenreRevealSourceError: Original source or ten markers are unavailable.
    """
    preview = discover_genre_source(slug, name, page_reader)
    embed_url = SPOTIFY_EMBED_URL_TEMPLATE.format(
        playlist_id=preview.source_playlist_id
    )
    return _GenrePlaylistSource(
        preview=preview,
        track_uris=_first_track_uris(page_reader(embed_url)),
    )


def parse_destination_playlist_id(reference: str | None) -> str:
    """Parse the configured Genre Reveal destination playlist."""
    try:
        return blast_from_past.parse_playlist_id(
            reference,
            setting_name="GENRE_REVEAL_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise GenreRevealConfigError(str(exc)) from exc


def append_genre_reveal_log(
    result: GenreRevealRunResult,
    path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one reviewable record after Spotify accepted the operation.

    Args:
        result: Original presented completion outcome.
        path: Original audit location.

    Raises:
        GenreRevealLogError: Original audit cannot be written.
    """
    record = result.model_dump(mode="json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise GenreRevealLogError(
            f"Could not write Genre Reveal log to {path}: {exc}"
        ) from exc


def process_next_genre(
    sp: Spotify,
    slug: str,
    name: str,
    destination_playlist_id: str,
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    page_reader: PageReader = read_public_page,
) -> GenreRevealRunResult:
    """Save one genre playlist and copy its first ten missing tracks.

    Args:
        sp: Caller-owned synchronous Spotify client.
        slug: Original genre identity.
        name: Original display name.
        destination_playlist_id: Original target identity.
        log_path: Original audit location.
        page_reader: Original public-page reader.

    Returns:
        Original presented completion outcome after its accepted audit.

    Raises:
        GenreRevealSourceError: Original source discovery fails.
        GenreRevealLogError: Original completion audit cannot be written.
        ValidationError: Original request values are invalid.
    """
    from spotify_manager.bootstrap.genre_run import run_genre_reveal

    return run_genre_reveal(
        sp, slug, name, destination_playlist_id, log_path, page_reader
    )


def _save_source_playlist(sp: Spotify, source: GenrePlaylistSource) -> None:
    sp._put(
        "me/library",
        args={"uris": source.preview.source_playlist_uri},
    )


def _append_source_tracks(
    sp: Spotify, destination_playlist_id: str, missing: tuple[str, ...]
) -> None:
    sp._post(
        f"playlists/{destination_playlist_id}/items",
        payload={"uris": list(missing)},
    )
