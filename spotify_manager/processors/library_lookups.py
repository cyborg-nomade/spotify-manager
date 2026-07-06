"""Library lookups: artist stats and album keep/remove evaluation.

These are *files-first*. The source of truth is ``YourLibrary.json`` (the
~2-weekly Spotify export), loaded via :func:`load_your_library_file`.

* :func:`get_artist_library_stats` is fully local - no Spotify API calls.
* :func:`evaluate_album` resolves the album to a Spotify **id** from the export
  (or you pass one in) and makes a single live call to fetch its track list,
  because the export does not store album track lists. "Liked" status is then
  decided locally by matching track ids against the export's liked tracks.

Matching against the export is exact (whitespace-stripped, case-insensitive) -
never a fuzzy search - so results are deterministic.
"""

from collections.abc import Callable

from spotipy import Spotify

# UFI
from spotify_manager.loaders_savers import load_album_tracks_cache
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.loaders_savers import save_album_tracks_cache
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile


ClientFactory = Callable[[], Spotify]


class ArtistNotFoundError(LookupError):
    """Raised when an artist id/name cannot be resolved in the library."""


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


def _all_items(sp: Spotify, page: dict) -> list[dict]:
    """Collect every item across a paginated spotipy response."""
    items = list(page["items"])
    while page.get("next"):
        page = sp.next(page)
        items.extend(page["items"])
    return items


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
    return [{"id": t.get("id"), "name": t["name"], "uri": t["uri"]} for t in raw if t]


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

    Kept when at least ``threshold`` (default 50%) of the album's tracks are
    liked, otherwise removed. The album is resolved to an id locally. Its track
    list comes from the local cache when available, otherwise from one Spotify
    API call (then cached). With a warm cache the whole call is offline.
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
            AlbumTrackLikedStatus(name=track["name"], uri=track["uri"], liked=is_liked)
        )

    total = len(statuses)
    ratio = (liked_count / total) if total else 0.0
    decision = "keep" if ratio >= threshold else "remove"

    return AlbumEvaluation(
        album_name=resolved_name or resolved_id,
        album_id=resolved_id,
        artist_name=resolved_artist,
        total_tracks=total,
        liked_tracks=liked_count,
        liked_ratio=ratio,
        threshold=threshold,
        decision=decision,
        tracks=statuses,
        source="files" if from_cache else "files+api",
        from_cache=from_cache,
    )
