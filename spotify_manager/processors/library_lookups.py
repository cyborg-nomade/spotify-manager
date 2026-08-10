"""Local and live artist stats and album keep/remove evaluation.

The original helpers remain available for file-based workflows. Their live
counterparts resolve names through Spotify and read Saved Albums and Liked
Songs status directly from the API.
"""

import re
from collections.abc import Callable
from math import floor
from typing import Literal
from urllib.parse import urlparse

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.loaders_savers import load_album_tracks_cache
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.loaders_savers import save_album_tracks_cache
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile


ClientFactory = Callable[[], Spotify]
SPOTIFY_SEARCH_LIMIT = 10
SPOTIFY_ARTIST_ALBUM_PAGE_SIZE = 50
SPOTIFY_ALBUM_BATCH_SIZE = 20
SPOTIFY_CONTAINS_BATCH_SIZE = 20
SPOTIFY_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{22}$")


def parse_spotify_lookup_reference(
    reference: str,
    resource: Literal["artist", "album"],
) -> tuple[str | None, str | None]:
    """Parse a Spotify name, id, URI, or share URL into lookup arguments."""
    value = reference.strip()
    if not value:
        raise ValueError(f"provide an {resource} name, ID, or Spotify link")

    uri_prefix = f"spotify:{resource}:"
    if value.casefold().startswith(uri_prefix):
        spotify_id = value[len(uri_prefix) :].strip()
        if SPOTIFY_ID_PATTERN.fullmatch(spotify_id):
            return None, spotify_id
        raise ValueError(f"invalid Spotify {resource} URI")

    parsed = urlparse(value)
    if parsed.netloc.casefold() in {"open.spotify.com", "www.open.spotify.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].casefold().startswith("intl-"):
            parts = parts[1:]
        if len(parts) >= 2 and parts[0].casefold() == resource:
            spotify_id = parts[1]
            if SPOTIFY_ID_PATTERN.fullmatch(spotify_id):
                return None, spotify_id
        raise ValueError(f"provide a Spotify {resource} share link")

    if SPOTIFY_ID_PATTERN.fullmatch(value):
        return None, value
    return value, None


class ArtistNotFoundError(LookupError):
    """Raised when an artist id/name cannot be resolved in the library."""


class AmbiguousArtistError(LookupError):
    """Raised when an artist name has several exact Spotify matches."""

    def __init__(self, message: str, candidates: list[dict]) -> None:
        """Store the human message and exact-name Spotify candidates."""
        super().__init__(message)
        self.candidates = candidates


class SpotifyLookupResponseError(RuntimeError):
    """Raised when Spotify returns malformed live lookup data."""


class TracklistUnavailableError(LookupError):
    """Raised when an album's tracks aren't cached and no client is available."""


class AlbumNotFoundError(LookupError):
    """Raised when an album id/name cannot be resolved in the library."""


class AmbiguousAlbumError(LookupError):
    """Raised when an album name matches more than one saved album."""

    def __init__(self, message: str, candidates: list[dict]) -> None:
        """Store the human message and the list of candidate albums."""
        super().__init__(message)
        self.candidates = candidates


def _norm(value: str) -> str:
    """Normalise a name for exact, case-insensitive matching."""
    return value.strip().casefold()


def _load_library(library: YourLibraryFile | None) -> YourLibraryFile:
    """Return the provided library or load YourLibrary.json."""
    return library if library is not None else load_your_library_file()


def _all_items(sp: Spotify, page: object) -> list[dict]:
    """Collect and validate every item across a paginated Spotify response."""
    items: list[dict] = []
    while True:
        if not isinstance(page, dict):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid paginated track data."
            )
        raw_items = page.get("items")
        if not isinstance(raw_items, list):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid paginated track data."
            )
        items.extend(item for item in raw_items if isinstance(item, dict))
        if not page.get("next"):
            return items
        if not raw_items:
            raise SpotifyLookupResponseError(
                "Spotify returned an empty track page with a next link."
            )
        page = sp.next(page)


def resolve_artist(
    library: YourLibraryFile,
    name: str | None = None,
    artist_id: str | None = None,
) -> tuple[str | None, str]:
    """Resolve an artist to ``(artist_id, artist_name)`` from the library.

    Track and album entries in the export carry only artist *names*, so the
    returned name is what counting is keyed on. ``artist_id`` is returned when
    the artist is among the followed artists (which do carry ids).
    """
    if not name and not artist_id:
        raise ValueError("provide an artist name or artist_id")

    if artist_id:
        for artist in library.artists:
            if artist.spotify_id == artist_id:
                return artist_id, artist.name
        raise ArtistNotFoundError(
            f"Artist id {artist_id!r} is not among your followed artists"
        )

    assert name is not None
    for artist in library.artists:
        if _norm(artist.name) == _norm(name):
            return artist.spotify_id, artist.name
    # Not followed, but tracks/albums can still be counted by name.
    return None, name


def get_artist_library_stats(
    name: str | None = None,
    artist_id: str | None = None,
    library: YourLibraryFile | None = None,
) -> ArtistLibraryStats:
    """Return liked-track and saved-release counts for an artist (local only)."""
    lib = _load_library(library)
    resolved_id, resolved_name = resolve_artist(lib, name=name, artist_id=artist_id)
    target = _norm(resolved_name)

    liked = sum(1 for track in lib.tracks if _norm(track.artist) == target)
    releases = sum(1 for album in lib.albums if _norm(album.artist) == target)

    return ArtistLibraryStats(
        artist_name=resolved_name,
        artist_id=resolved_id,
        liked_tracks=liked,
        saved_releases=releases,
        source="files",
    )


def _spotify_artist_identity(raw: object) -> tuple[str, str] | None:
    """Return a Spotify artist id/name pair from one response object."""
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    return (spotify_id, name) if spotify_id and name else None


def resolve_live_artist(
    sp: Spotify,
    *,
    name: str | None = None,
    artist_id: str | None = None,
) -> tuple[str, str]:
    """Resolve exactly one artist from Spotify without consulting local files."""
    if not name and not artist_id:
        raise ValueError("provide name or artist_id")

    if artist_id:
        try:
            identity = _spotify_artist_identity(sp.artist(artist_id))
        except SpotifyException as exc:
            if exc.http_status == 404:
                raise ArtistNotFoundError(
                    f"Spotify artist id {artist_id!r} was not found."
                ) from exc
            raise
        if identity is None:
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid artist data for {artist_id!r}."
            )
        return identity

    assert name is not None
    escaped_name = name.replace('"', " ").strip()
    response = sp.search(
        q=f'artist:"{escaped_name}"',
        type="artist",
        limit=SPOTIFY_SEARCH_LIMIT,
        offset=0,
    )
    page = response.get("artists") if isinstance(response, dict) else None
    raw_items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(raw_items, list):
        raise SpotifyLookupResponseError(
            f"Spotify returned invalid artist search data for {name!r}."
        )

    expected = _norm(name)
    matches = list(
        dict.fromkeys(
            identity
            for raw in raw_items
            if (identity := _spotify_artist_identity(raw)) is not None
            and _norm(identity[1]) == expected
        )
    )
    if not matches:
        raise ArtistNotFoundError(f"No exact Spotify artist named {name!r} was found.")
    if len(matches) > 1:
        candidates = [
            {"artist": artist_name, "id": spotify_id}
            for spotify_id, artist_name in matches
        ]
        raise AmbiguousArtistError(
            f"Spotify returned {len(matches)} exact artists named {name!r}; "
            "use the Spotify artist ID to disambiguate.",
            candidates,
        )
    return matches[0]


def _primary_artist_id(raw: object) -> str | None:
    """Return the first credited artist id in one Spotify object."""
    if not isinstance(raw, dict) or not isinstance(raw.get("artists"), list):
        return None
    artists = raw["artists"]
    if not artists or not isinstance(artists[0], dict):
        return None
    return str(artists[0].get("id") or "").strip() or None


def _live_artist_release_ids(sp: Spotify, artist_id: str) -> list[str]:
    """Return unique catalog releases where the artist is credited first."""
    release_ids: dict[str, None] = {}
    offset = 0
    while True:
        response = sp.artist_albums(
            artist_id,
            include_groups="album,single,compilation,appears_on",
            limit=SPOTIFY_ARTIST_ALBUM_PAGE_SIZE,
            offset=offset,
        )
        raw_items = response.get("items") if isinstance(response, dict) else None
        if not isinstance(raw_items, list):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid artist release data."
            )
        for raw in raw_items:
            if not isinstance(raw, dict) or _primary_artist_id(raw) != artist_id:
                continue
            release_id = str(raw.get("id") or "").strip()
            if release_id:
                release_ids[release_id] = None
        if not response.get("next"):
            break
        if not raw_items:
            raise SpotifyLookupResponseError(
                "Spotify returned an empty artist release page with a next link."
            )
        offset += len(raw_items)
    return list(release_ids)


def _live_primary_track_ids(
    sp: Spotify,
    artist_id: str,
    release_ids: list[str],
) -> list[str]:
    """Return unique catalog track ids where the artist is credited first."""
    track_ids: dict[str, None] = {}
    for start in range(0, len(release_ids), SPOTIFY_ALBUM_BATCH_SIZE):
        batch = release_ids[start : start + SPOTIFY_ALBUM_BATCH_SIZE]
        response = sp.albums(batch)
        raw_albums = response.get("albums") if isinstance(response, dict) else None
        if not isinstance(raw_albums, list):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid batched album data."
            )
        for raw_album in raw_albums:
            if not isinstance(raw_album, dict):
                continue
            page: object = raw_album.get("tracks")
            while True:
                if not isinstance(page, dict):
                    raise SpotifyLookupResponseError(
                        "Spotify returned invalid album track data."
                    )
                raw_tracks = page.get("items")
                if not isinstance(raw_tracks, list):
                    raise SpotifyLookupResponseError(
                        "Spotify returned invalid album track data."
                    )
                for raw_track in raw_tracks:
                    if _primary_artist_id(raw_track) != artist_id:
                        continue
                    if not isinstance(raw_track, dict):
                        continue
                    track_id = str(raw_track.get("id") or "").strip()
                    if track_id:
                        track_ids[track_id] = None
                if not page.get("next"):
                    break
                if not raw_tracks:
                    raise SpotifyLookupResponseError(
                        "Spotify returned an empty album track page with a next link."
                    )
                page = sp.next(page)
    return list(track_ids)


def _count_live_contains(
    ids: list[str],
    contains: Callable[[list[str]], object],
    resource: str,
) -> int:
    """Count live saved statuses in conservative Spotify-sized batches."""
    count = 0
    for start in range(0, len(ids), SPOTIFY_CONTAINS_BATCH_SIZE):
        batch = ids[start : start + SPOTIFY_CONTAINS_BATCH_SIZE]
        response = contains(batch)
        if not isinstance(response, list) or len(response) != len(batch):
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid {resource} statuses."
            )
        count += sum(bool(saved) for saved in response)
    return count


def get_live_artist_library_stats(
    sp: Spotify,
    *,
    name: str | None = None,
    artist_id: str | None = None,
) -> ArtistLibraryStats:
    """Count one artist's Liked Songs and Saved Albums from live Spotify state."""
    resolved_id, resolved_name = resolve_live_artist(
        sp,
        name=name,
        artist_id=artist_id,
    )
    release_ids = _live_artist_release_ids(sp, resolved_id)
    saved_releases = _count_live_contains(
        release_ids,
        sp.current_user_saved_albums_contains,
        "Saved Albums",
    )
    track_ids = _live_primary_track_ids(sp, resolved_id, release_ids)
    liked_tracks = _count_live_contains(
        track_ids,
        sp.current_user_saved_tracks_contains,
        "Liked Songs",
    )
    return ArtistLibraryStats(
        artist_name=resolved_name,
        artist_id=resolved_id,
        liked_tracks=liked_tracks,
        saved_releases=saved_releases,
        source="spotify-live",
    )


def resolve_album(
    library: YourLibraryFile,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Resolve an album to ``(album_id, album_name, artist_name)``.

    Resolution is by Spotify id (if given) or by exact name against saved
    albums. A name matching several distinct albums raises
    :class:`AmbiguousAlbumError` so the caller can disambiguate.
    """
    if not name and not album_id:
        raise ValueError("provide an album name or album_id")

    if album_id:
        for album in library.albums:
            if album.spotify_id == album_id:
                return album_id, album.album, album.artist
        # Id not saved locally; still evaluable via the API.
        return album_id, None, None

    assert name is not None
    matches = [a for a in library.albums if _norm(a.album) == _norm(name)]
    if artist:
        matches = [a for a in matches if _norm(a.artist) == _norm(artist)]
    if not matches:
        suffix = f" by {artist!r}" if artist else ""
        raise AlbumNotFoundError(
            f"No saved album named {name!r}{suffix}. "
            "Pass album_id to evaluate one you have not saved."
        )

    unique = {a.spotify_id: a for a in matches}
    if len(unique) > 1:
        candidates = [
            {"album": a.album, "artist": a.artist, "id": a.spotify_id}
            for a in unique.values()
        ]
        raise AmbiguousAlbumError(
            f"{len(unique)} saved albums named {name!r}; "
            "disambiguate with artist or album_id.",
            candidates,
        )

    album = next(iter(unique.values()))
    return album.spotify_id, album.album, album.artist


def _fetch_album_tracks(sp: Spotify, album_id: str) -> list[dict]:
    """Fetch and minimise an album's track list from the Spotify API."""
    raw = _all_items(sp, sp.album_tracks(album_id, limit=50))
    tracks = []
    for track in raw:
        name = str(track.get("name") or "").strip()
        uri = str(track.get("uri") or "").strip()
        if not name or not uri:
            raise SpotifyLookupResponseError(
                f"Spotify returned incomplete track data for album {album_id!r}."
            )
        tracks.append({"id": track.get("id"), "name": name, "uri": uri})
    return tracks


def get_album_tracklist(
    album_id: str,
    sp: Spotify | None = None,
    client_factory: ClientFactory | None = None,
    use_cache: bool = True,
    refresh_cache: bool = False,
) -> tuple[list[dict], bool]:
    """Return ``(tracks, from_cache)`` for an album, caching API results.

    On a cache hit no Spotify client is needed. On a miss the client is taken
    from ``sp`` or built lazily from ``client_factory``; the fetched track list
    is then written to the local cache (unless ``use_cache`` is False).
    """
    cache = load_album_tracks_cache() if use_cache else {}
    if use_cache and not refresh_cache and album_id in cache:
        return cache[album_id], True

    client = sp if sp is not None else (client_factory() if client_factory else None)
    if client is None:
        raise TracklistUnavailableError(
            f"Album {album_id!r} is not cached and no Spotify client is available."
        )

    tracks = _fetch_album_tracks(client, album_id)
    if use_cache:
        cache[album_id] = tracks
        save_album_tracks_cache(cache)
    return tracks, False


def required_liked_tracks(total_tracks: int, threshold: float) -> int:
    """Return the whole-track keep threshold for an album."""
    if total_tracks <= 0:
        return 1
    if threshold <= 0:
        return 0
    return max(1, floor(total_tracks * threshold))


def evaluate_album(
    sp: Spotify | None = None,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
    library: YourLibraryFile | None = None,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
    client_factory: ClientFactory | None = None,
) -> AlbumEvaluation:
    """Decide whether an album should be kept based on liked tracks.

    Kept when the liked-track count reaches the whole-track threshold. For the
    default 50%, odd-sized albums require half of ``n - 1`` tracks. The album is
    resolved to an id locally. Its track list comes from the local cache when
    available, otherwise from one Spotify API call (then cached). With a warm
    cache the whole call is offline.
    """
    lib = _load_library(library)
    resolved_id, resolved_name, resolved_artist = resolve_album(
        lib, name=name, album_id=album_id, artist=artist
    )

    liked_ids = {track.spotify_id for track in lib.tracks}

    tracks, from_cache = get_album_tracklist(
        resolved_id,
        sp=sp,
        client_factory=client_factory,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
    )

    statuses: list[AlbumTrackLikedStatus] = []
    liked_count = 0
    for track in tracks:
        is_liked = track.get("id") in liked_ids
        liked_count += int(is_liked)
        statuses.append(
            AlbumTrackLikedStatus(
                name=track["name"],
                uri=track["uri"],
                liked=is_liked,
                spotify_id=track.get("id"),
            )
        )

    total = len(statuses)
    ratio = (liked_count / total) if total else 0.0
    required_liked_count = required_liked_tracks(total, threshold)
    decision = "keep" if liked_count >= required_liked_count else "remove"

    return AlbumEvaluation(
        album_name=resolved_name or resolved_id,
        album_id=resolved_id,
        artist_name=resolved_artist,
        total_tracks=total,
        liked_tracks=liked_count,
        required_liked_tracks=required_liked_count,
        liked_ratio=ratio,
        threshold=threshold,
        decision=decision,
        tracks=statuses,
        source="files" if from_cache else "files+api",
        from_cache=from_cache,
    )


def resolve_live_album(
    sp: Spotify,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
) -> tuple[str, str, str | None]:
    """Resolve an album from Spotify search or a direct Spotify id."""
    if not name and not album_id:
        raise ValueError("provide name or album_id")

    if album_id:
        try:
            raw_album = sp.album(album_id)
        except SpotifyException as exc:
            if exc.http_status == 404:
                raise AlbumNotFoundError(
                    f"Spotify album id {album_id!r} was not found."
                ) from exc
            raise
        if not isinstance(raw_album, dict):
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid album data for {album_id!r}."
            )
    else:
        assert name is not None
        escaped_name = name.replace('"', " ").strip()
        query = f'album:"{escaped_name}"'
        if artist:
            query += f' artist:"{artist.replace(chr(34), " ").strip()}"'
        response = sp.search(
            q=query,
            type="album",
            limit=SPOTIFY_SEARCH_LIMIT,
            offset=0,
        )
        page = response.get("albums") if isinstance(response, dict) else None
        raw_items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(raw_items, list):
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid album search data for {name!r}."
            )
        expected_name = _norm(name)
        expected_artist = _norm(artist) if artist else None
        matches: dict[str, dict] = {}
        for raw in raw_items:
            if (
                not isinstance(raw, dict)
                or _norm(str(raw.get("name") or "")) != expected_name
            ):
                continue
            primary_artist = None
            if isinstance(raw.get("artists"), list) and raw["artists"]:
                first_artist = raw["artists"][0]
                if isinstance(first_artist, dict):
                    primary_artist = str(first_artist.get("name") or "").strip()
            if (
                expected_artist is not None
                and _norm(primary_artist or "") != expected_artist
            ):
                continue
            candidate_id = str(raw.get("id") or "").strip()
            if candidate_id:
                matches[candidate_id] = raw
        if not matches:
            suffix = f" by {artist!r}" if artist else ""
            raise AlbumNotFoundError(
                f"No exact Spotify album named {name!r}{suffix} was found."
            )
        if len(matches) > 1:
            candidates = []
            for candidate_id, raw in matches.items():
                raw_artists = raw.get("artists")
                primary_artist = (
                    str(raw_artists[0].get("name") or "")
                    if isinstance(raw_artists, list)
                    and raw_artists
                    and isinstance(raw_artists[0], dict)
                    else ""
                )
                candidates.append(
                    {
                        "album": str(raw.get("name") or name),
                        "artist": primary_artist,
                        "id": candidate_id,
                    }
                )
            raise AmbiguousAlbumError(
                f"Spotify returned {len(matches)} exact albums named {name!r}; "
                "disambiguate with artist or album ID.",
                candidates,
            )
        album_id, raw_album = next(iter(matches.items()))

    resolved_id = str(raw_album.get("id") or album_id or "").strip()
    resolved_name = str(raw_album.get("name") or "").strip()
    raw_artists = raw_album.get("artists")
    resolved_artist = (
        str(raw_artists[0].get("name") or "").strip()
        if isinstance(raw_artists, list)
        and raw_artists
        and isinstance(raw_artists[0], dict)
        else None
    )
    if not resolved_id or not resolved_name:
        raise SpotifyLookupResponseError("Spotify returned incomplete album data.")
    return resolved_id, resolved_name, resolved_artist or None


def evaluate_album_live(
    sp: Spotify,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Evaluate one album using a fresh Spotify track list and Liked statuses."""
    resolved_id, resolved_name, resolved_artist = resolve_live_album(
        sp,
        name=name,
        album_id=album_id,
        artist=artist,
    )
    tracks = _fetch_album_tracks(sp, resolved_id)
    track_ids = [str(track.get("id")) for track in tracks if track.get("id")]
    liked_by_id: dict[str, bool] = {}
    for start in range(0, len(track_ids), SPOTIFY_CONTAINS_BATCH_SIZE):
        batch = track_ids[start : start + SPOTIFY_CONTAINS_BATCH_SIZE]
        response = sp.current_user_saved_tracks_contains(batch)
        if not isinstance(response, list) or len(response) != len(batch):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid Liked Songs statuses."
            )
        liked_by_id.update(
            {
                track_id: bool(liked)
                for track_id, liked in zip(batch, response, strict=True)
            }
        )

    statuses = [
        AlbumTrackLikedStatus(
            name=str(track["name"]),
            uri=str(track["uri"]),
            liked=liked_by_id.get(str(track.get("id")), False),
            spotify_id=str(track.get("id")) if track.get("id") else None,
        )
        for track in tracks
    ]
    liked_count = sum(status.liked for status in statuses)
    total = len(statuses)
    required_liked_count = required_liked_tracks(total, threshold)
    return AlbumEvaluation(
        album_name=resolved_name,
        album_id=resolved_id,
        artist_name=resolved_artist,
        total_tracks=total,
        liked_tracks=liked_count,
        required_liked_tracks=required_liked_count,
        liked_ratio=liked_count / total if total else 0.0,
        threshold=threshold,
        decision="keep" if liked_count >= required_liked_count else "remove",
        tracks=statuses,
        source="spotify-live",
        from_cache=False,
    )
