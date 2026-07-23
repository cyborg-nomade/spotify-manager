"""Progress and Spotify actions for the Every Noise genre-reveal route."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError
from pydantic import field_validator
from spotipy import Spotify

# UFI
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


class GenreRevealStateError(RuntimeError):
    """Raised when genre-reveal state cannot be read or written."""


class GenreRevealSourceError(RuntimeError):
    """Raised when an Every Noise or Spotify public page cannot be resolved."""


class GenreRevealConfigError(RuntimeError):
    """Raised when the destination playlist is not configured."""


class GenreRevealLogError(RuntimeError):
    """Raised when a completed operation cannot be recorded."""


class GenreRevealCompleteError(RuntimeError):
    """Raised when the nearest-neighbour route has no incomplete genres."""


def _validate_completed_slugs(slugs: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        if (
            not slug
            or len(slug) > MAX_SLUG_LENGTH
            or slug != slug.strip()
            or any(character.isspace() for character in slug)
        ):
            raise ValueError("completed entries must be valid Every Noise slugs")
        if slug not in seen:
            seen.add(slug)
            cleaned.append(slug)
    return cleaned


class GenreRevealStateUpdate(BaseModel):
    """Client-provided genre-reveal progress."""

    completed: list[str] = Field(default_factory=list, max_length=MAX_GENRES)
    hide_done: bool = False

    @field_validator("completed")
    @classmethod
    def validate_completed(cls, value: list[str]) -> list[str]:
        """Validate and de-duplicate completed genre slugs."""
        return _validate_completed_slugs(value)


class GenreRevealState(GenreRevealStateUpdate):
    """Persisted genre-reveal progress with server metadata."""

    version: int = 1
    updated_at: datetime | None = None


class GenreRevealRunRequest(BaseModel):
    """The first incomplete genre selected by the web route."""

    slug: str = Field(min_length=1, max_length=MAX_SLUG_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_GENRE_NAME_LENGTH)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        """Apply the same slug rules used by persisted progress."""
        validated = _validate_completed_slugs([value])[0]
        if re.fullmatch(r"[a-z0-9]+", validated) is None:
            raise ValueError(
                "genre slug must contain only lowercase letters and digits"
            )
        return validated

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject empty or padded display names."""
        if value != value.strip():
            raise ValueError("genre name must not have leading or trailing whitespace")
        return value


class GenreRevealSourcePreview(BaseModel):
    """Public links discovered for one Every Noise genre."""

    slug: str
    name: str
    every_noise_url: str
    source_playlist_id: str
    source_playlist_uri: str
    source_playlist_url: str


class GenreRevealRunResult(GenreRevealSourcePreview):
    """Outcome of one completed genre-reveal Spotify operation."""

    destination_playlist_id: str
    source_track_uris: list[str]
    added_track_uris: list[str]
    already_present_track_uris: list[str]
    completed_at: datetime


@dataclass(frozen=True)
class GenreRouteEntry:
    """One ordered entry in the nearest-neighbour route."""

    name: str
    slug: str
    position: int


@dataclass(frozen=True)
class _GenrePlaylistSource:
    """Resolved source playlist and its ordered first tracks."""

    preview: GenreRevealSourcePreview
    track_uris: tuple[str, ...]


class _EveryNoisePlaylistParser(HTMLParser):
    """Extract Spotify playlist links and their labels from Every Noise HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Collect Spotify playlist anchors in document order."""
        if tag.casefold() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        title = attributes.get("title") or ""
        if SPOTIFY_PLAYLIST_URL_PATTERN.fullmatch(href):
            self.links.append((href, title))


def load_genre_reveal_state(
    path: Path = DEFAULT_STATE_PATH,
) -> GenreRevealState:
    """Load persisted progress, returning a new empty state when absent."""
    if not path.exists():
        return GenreRevealState()
    try:
        return GenreRevealState.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not read genre-reveal state from {path}: {exc}"
        ) from exc
    except ValidationError as exc:
        raise GenreRevealStateError(f"Genre-reveal state is invalid: {path}") from exc


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
            key=lambda candidate: candidate.name,
        )
        for stale_backup in backups[:-MAX_STATE_BACKUPS]:
            stale_backup.unlink()
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not back up genre-reveal state from {path}: {exc}"
        ) from exc


def save_genre_reveal_state(
    update: GenreRevealStateUpdate,
    path: Path = DEFAULT_STATE_PATH,
) -> GenreRevealState:
    """Back up the current state, then replace it atomically."""
    existing_contents: str | None = None
    if path.exists():
        try:
            existing_contents = path.read_text(encoding="utf-8")
            existing_state = GenreRevealState.model_validate_json(existing_contents)
        except OSError as exc:
            raise GenreRevealStateError(
                f"Could not read genre-reveal state from {path}: {exc}"
            ) from exc
        except ValidationError as exc:
            raise GenreRevealStateError(
                f"Genre-reveal state is invalid: {path}"
            ) from exc

        if (
            existing_state.completed == update.completed
            and existing_state.hide_done == update.hide_done
        ):
            return existing_state

    state = GenreRevealState(
        completed=update.completed,
        hide_done=update.hide_done,
        updated_at=datetime.now(UTC),
    )
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if existing_contents is not None:
            _backup_genre_reveal_state(path, existing_contents)
        temporary_path.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not write genre-reveal state to {path}: {exc}"
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return state


def load_genre_route(
    path: Path = DEFAULT_ROUTE_PATH,
) -> tuple[GenreRouteEntry, ...]:
    """Load the preserved ordered route from its standalone HTML asset."""
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenreRevealStateError(
            f"Could not read genre route from {path}: {exc}"
        ) from exc

    match = GENRE_ROUTE_PATTERN.search(html)
    if match is None:
        raise GenreRevealStateError(f"Genre route data was not found in {path}.")
    try:
        raw_route = json.loads(match.group("route"))
    except json.JSONDecodeError as exc:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.") from exc
    if not isinstance(raw_route, list) or len(raw_route) > MAX_GENRES:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.")

    route: list[GenreRouteEntry] = []
    try:
        for position, raw_entry in enumerate(raw_route, start=1):
            if not isinstance(raw_entry, list) or len(raw_entry) < 2:
                raise ValueError
            request = GenreRevealRunRequest(
                name=str(raw_entry[0]),
                slug=str(raw_entry[1]),
            )
            route.append(
                GenreRouteEntry(
                    name=request.name,
                    slug=request.slug,
                    position=position,
                )
            )
    except (TypeError, ValueError, ValidationError) as exc:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.") from exc
    return tuple(route)


def first_incomplete_genre(
    state: GenreRevealState,
    route_path: Path = DEFAULT_ROUTE_PATH,
) -> GenreRouteEntry:
    """Return the first route entry not present in persisted progress."""
    completed = set(state.completed)
    for entry in load_genre_route(route_path):
        if entry.slug not in completed:
            return entry
    raise GenreRevealCompleteError("Every genre in the route is complete.")


def mark_genre_completed(
    slug: str,
    path: Path = DEFAULT_STATE_PATH,
) -> GenreRevealState:
    """Add one slug to the latest persisted state without changing its settings."""
    state = load_genre_reveal_state(path)
    if slug not in state.completed:
        state.completed.append(slug)
    return save_genre_reveal_state(
        GenreRevealStateUpdate(
            completed=state.completed,
            hide_done=state.hide_done,
        ),
        path,
    )


def read_public_page(url: str) -> str:
    """Fetch one public HTML page with a bounded timeout."""
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
    """Find the primary Spotify playlist linked by an Every Noise genre page."""
    request = GenreRevealRunRequest(slug=slug, name=name)
    every_noise_url = EVERY_NOISE_URL_TEMPLATE.format(slug=request.slug)
    parser = _EveryNoisePlaylistParser()
    parser.feed(page_reader(every_noise_url))

    primary_url = next(
        (
            href
            for href, title in parser.links
            if title.casefold().startswith("listen to the sound of ")
            and title.casefold().endswith(" on spotify")
        ),
        None,
    )
    if primary_url is None:
        raise GenreRevealSourceError(
            f"Every Noise has no primary Spotify playlist for {request.name}."
        )

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
    track_uris = tuple(dict.fromkeys(SPOTIFY_TRACK_URI_PATTERN.findall(embed_html)))
    if len(track_uris) < SOURCE_TRACK_COUNT:
        raise GenreRevealSourceError(
            "Spotify's public playlist page did not expose the first "
            f"{SOURCE_TRACK_COUNT} tracks."
        )
    return track_uris[:SOURCE_TRACK_COUNT]


def load_genre_playlist_source(
    slug: str,
    name: str,
    page_reader: PageReader = read_public_page,
) -> _GenrePlaylistSource:
    """Resolve a genre's source playlist and its first ten ordered tracks."""
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
    """Append one reviewable record after Spotify accepted the operation."""
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
    """Save one genre playlist and copy its first ten missing tracks."""
    source = load_genre_playlist_source(slug, name, page_reader)
    destination = blast_from_past.load_playlist_state(sp, destination_playlist_id)
    already_present = tuple(
        uri
        for uri in source.track_uris
        if uri.rsplit(":", maxsplit=1)[-1] in destination.track_ids
    )
    missing = tuple(uri for uri in source.track_uris if uri not in already_present)

    sp._put(
        "me/library",
        args={"uris": source.preview.source_playlist_uri},
    )
    if missing:
        sp._post(
            f"playlists/{destination_playlist_id}/items",
            payload={"uris": list(missing)},
        )

    result = GenreRevealRunResult(
        **source.preview.model_dump(),
        destination_playlist_id=destination_playlist_id,
        source_track_uris=list(source.track_uris),
        added_track_uris=list(missing),
        already_present_track_uris=list(already_present),
        completed_at=datetime.now(UTC),
    )
    append_genre_reveal_log(result, log_path)
    return result
