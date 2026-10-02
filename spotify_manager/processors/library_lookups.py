"""Local and live artist stats and album keep/remove evaluation.

The original helpers remain available for file-based workflows. Their live
counterparts resolve names through Spotify and read Saved Albums and Liked
Songs status directly from the API.
"""

import re
from collections.abc import Callable
from functools import partial
from typing import Literal

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application import library_lookup_run as lookup_workflow
from spotify_manager.application import lookup_resolution
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.bootstrap import library_lookups as lookup_composition

# UFI
from spotify_manager.domain import albums as album_policy
from spotify_manager.domain import lookup_selection
from spotify_manager.domain.lookup_values import (
    AlbumNotFoundError as AlbumNotFoundError,
)
from spotify_manager.domain.lookup_values import (
    AmbiguousAlbumError as AmbiguousAlbumError,
)
from spotify_manager.domain.lookup_values import (
    AmbiguousArtistError as AmbiguousArtistError,
)
from spotify_manager.domain.lookup_values import (
    ArtistNotFoundError as ArtistNotFoundError,
)
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import (
    SpotifyLookupResponseError as SpotifyLookupResponseError,
)
from spotify_manager.domain.lookup_values import (
    TracklistUnavailableError as TracklistUnavailableError,
)
from spotify_manager.infrastructure import lookup_catalog
from spotify_manager.infrastructure import lookup_records
from spotify_manager.infrastructure import lookup_reference
from spotify_manager.loaders_savers import (
    load_album_tracks_cache as load_album_tracks_cache,
)
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.loaders_savers import (
    save_album_tracks_cache as save_album_tracks_cache,
)
from spotify_manager.models.lookups import AlbumEvaluation
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
    resource: Literal["artist", "album", "track"],
) -> tuple[str | None, str | None]:
    """Parse a Spotify name, id, URI, or share URL into lookup arguments.

    Args:
        reference: Original name, bare identity, URI or Spotify share link.
        resource: Required original Spotify resource kind.

    Returns:
        Original parse spotify lookup reference result.
    """
    return lookup_reference.parse(reference, resource, SPOTIFY_ID_PATTERN)


def _norm(value: str) -> str:
    """Normalise a name for exact, case-insensitive matching."""
    return lookup_selection.exact_name(value)


def _load_library(library: YourLibraryFile | None) -> YourLibraryFile:
    """Return the provided library or load YourLibrary.json."""
    return library if library is not None else load_your_library_file()


def _all_items(sp: Spotify, page: object) -> list[dict[str, object]]:
    """Collect and validate every item across a paginated Spotify response."""
    return lookup_catalog.all_items(partial(_next_object_page, sp), page)


def _spotify_artist_identity(raw: object) -> tuple[str, str] | None:
    """Return a Spotify artist id/name pair from one response object."""
    return lookup_records.artist_identity(raw)


def resolve_live_artist(
    sp: Spotify,
    *,
    name: str | None = None,
    artist_id: str | None = None,
) -> tuple[str, str]:
    """Resolve exactly one artist from Spotify without consulting local files.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        name: Original optional exact display name.
        artist_id: Original direct artist identity, taking precedence over a name.

    Returns:
        Original resolve live artist result.
    """
    return lookup_resolution.artist(
        lookup_composition.artist_lookup(sp), name, artist_id
    )


def _primary_artist_id(raw: object) -> str | None:
    """Return the first credited artist id in one Spotify object."""
    return lookup_records.primary_artist_id(raw)


def _live_artist_release_ids(sp: Spotify, artist_id: str) -> list[str]:
    """Return unique catalog releases where the artist is credited first."""
    return lookup_catalog.releases(
        partial(_artist_release_page, sp, artist_id), artist_id
    )


def _live_primary_track_ids(
    sp: Spotify,
    artist_id: str,
    release_ids: list[str],
) -> list[str]:
    """Return unique catalog track ids where the artist is credited first."""
    return lookup_catalog.primary_tracks(
        partial(_album_batch, sp),
        partial(_next_album_track_page, sp),
        artist_id,
        release_ids,
        SPOTIFY_ALBUM_BATCH_SIZE,
    )


def _count_live_contains(
    ids: list[str],
    contains: Callable[[list[str]], object],
    resource: str,
) -> int:
    """Count live saved statuses in conservative Spotify-sized batches."""
    return lookup_workflow.count_contains(
        ids, contains, resource, SPOTIFY_CONTAINS_BATCH_SIZE
    )


def get_live_artist_library_stats(
    sp: Spotify,
    *,
    name: str | None = None,
    artist_id: str | None = None,
) -> ArtistLibraryStats:
    """Count one artist's Liked Songs and Saved Albums from live Spotify state.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        name: Original optional exact display name.
        artist_id: Original direct artist identity, taking precedence over a name.

    Returns:
        Original get live artist library stats result.
    """
    return lookup_workflow.artist_statistics(
        lookup_composition.artist_statistics(sp, name, artist_id)
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

    Args:
        library: Original caller-supplied local export, or the original file fallback.
        name: Original optional exact display name.
        album_id: Original direct album identity, taking precedence over a name.
        artist: Original optional primary artist constraint.

    Returns:
        Original resolve album result.
    """
    return lookup_selection.local_album(library.albums, name, album_id, artist)


def _fetch_album_tracks(sp: Spotify, album_id: str) -> list[LookupTrack]:
    """Fetch and minimise an album's track list from the Spotify API."""
    rows = _all_items(sp, sp.album_tracks(album_id, limit=50))
    return lookup_catalog.minimize_tracks(rows, album_id)


def get_album_tracklist(
    album_id: str,
    sp: Spotify | None = None,
    client_factory: ClientFactory | None = None,
    use_cache: bool = True,
    refresh_cache: bool = False,
) -> tuple[list[LookupTrack], bool]:
    """Return ``(tracks, from_cache)`` for an album, caching API results.

    On a cache hit no Spotify client is needed. On a miss the client is taken
    from ``sp`` or built lazily from ``client_factory``; the fetched track list
    is then written to the local cache (unless ``use_cache`` is False).

    Args:
        album_id: Original direct album identity, taking precedence over a name.
        sp: Caller-owned original synchronous Spotify client.
        client_factory: Original lazy client acquisition after cache-hit checks.
        use_cache: Original cache read and publication flag.
        refresh_cache: Bypass original cache hits while retaining cache publication.

    Returns:
        Original get album tracklist result.
    """
    return lookup_workflow.tracklist(
        lookup_composition.cached_tracks(sp, client_factory),
        album_id,
        use_cache,
        refresh_cache,
    )


def required_liked_tracks(total_tracks: int, threshold: float) -> int:
    """Return the legacy album keep threshold through the pure policy.

    Args:
        total_tracks: Observed album size.
        threshold: Required liked proportion.

    Returns:
        Minimum liked-track count.

    Raises:
        ValueError: A positive-size album has a NaN threshold.
        OverflowError: A positive-size album has positive infinite threshold.
    """
    return album_policy.required_liked_tracks(total_tracks, threshold)


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

    Args:
        sp: Caller-owned original synchronous Spotify client.
        name: Original optional exact display name.
        album_id: Original direct album identity, taking precedence over a name.
        artist: Original optional primary artist constraint.
        library: Original caller-supplied local export, or the original file fallback.
        threshold: Original retention proportion.
        use_cache: Original cache read and publication flag.
        refresh_cache: Bypass original cache hits while retaining cache publication.
        client_factory: Original lazy client acquisition after cache-hit checks.

    Returns:
        Original evaluate album result.
    """
    return lookup_workflow.evaluate_local(
        lookup_composition.local_album(sp, client_factory, use_cache, refresh_cache),
        name,
        album_id,
        artist,
        library,
        threshold,
    )


def resolve_live_album(
    sp: Spotify,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
) -> tuple[str, str, str | None]:
    """Resolve an album from Spotify search or a direct Spotify id.

    Args:
        sp: Caller-owned original synchronous Spotify client.
        name: Original optional exact display name.
        album_id: Original direct album identity, taking precedence over a name.
        artist: Original optional primary artist constraint.

    Returns:
        Original resolve live album result.
    """
    return lookup_resolution.album(
        lookup_composition.album_lookup(sp), name, album_id, artist
    )


def load_live_liked_statuses(sp: Spotify, track_ids: list[str]) -> dict[str, bool]:
    """Read fresh membership with the album instrument's original batches.

    Args:
        sp: Existing synchronous client.
        track_ids: Ordered identifiers, including duplicates.

    Returns:
        Last observed boolean status per identifier.

    Raises:
        SpotifyLookupResponseError: A status response has the wrong shape or length.
    """
    return lookup_resolution.liked_statuses(
        track_ids, partial(_live_liked_statuses, sp), SPOTIFY_CONTAINS_BATCH_SIZE
    )


def evaluate_album_live(
    sp: Spotify,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Evaluate live album observations through the typed application use case.

    Args:
        sp: Existing synchronous client.
        name: Exact name when no identifier is supplied.
        album_id: Direct identifier, taking precedence over name.
        artist: Optional primary-artist disambiguation.
        threshold: Original retention threshold.

    Returns:
        The unchanged CLI and HTTP album evaluation model.

    Raises:
        AlbumNotFoundError: No album matches the reference.
        AmbiguousAlbumError: Several albums match the name.
        SpotifyLookupResponseError: A response fails existing validation.
        ValueError: Input or the numeric threshold is invalid.
    """
    from spotify_manager.bootstrap.albums import evaluate_live_album

    return evaluate_live_album(
        sp, name=name, album_id=album_id, artist=artist, threshold=threshold
    )


def _direct_artist_identity(sp: Spotify, identifier: str) -> tuple[str, str] | None:
    try:
        return lookup_records.artist_identity(sp.artist(identifier))
    except SpotifyException as error:
        if error.http_status == 404:
            raise ArtistNotFoundError(
                f"Spotify artist id {identifier!r} was not found."
            ) from error
        raise


def _artist_search_items(sp: Spotify, name: str) -> list[object]:
    escaped = name.replace('"', " ").strip()
    response = sp.search(
        q=f'artist:"{escaped}"', type="artist", limit=SPOTIFY_SEARCH_LIMIT, offset=0
    )
    return lookup_records.search_items(
        response,
        "artists",
        f"Spotify returned invalid artist search data for {name!r}.",
    )


def _next_object_page(sp: Spotify, page: object) -> object:
    return sp.next(page)


def _artist_release_page(sp: Spotify, identifier: str, offset: int) -> object:
    return sp.artist_albums(
        identifier,
        include_groups="album,single,compilation,appears_on",
        limit=SPOTIFY_ARTIST_ALBUM_PAGE_SIZE,
        offset=offset,
    )


def _album_batch(sp: Spotify, identifiers: list[str]) -> object:
    return sp.albums(identifiers)


def _next_album_track_page(sp: Spotify, page: object) -> object:
    return sp.next(page)


def _saved_artist_statuses(sp: Spotify, identifiers: list[str]) -> object:
    return sp.current_user_saved_albums_contains(identifiers)


def _liked_artist_statuses(sp: Spotify, identifiers: list[str]) -> object:
    return sp.current_user_saved_tracks_contains(identifiers)


def _direct_album(sp: Spotify, identifier: str) -> LiveAlbumCandidate:
    try:
        raw = sp.album(identifier)
    except SpotifyException as error:
        if error.http_status == 404:
            raise AlbumNotFoundError(
                f"Spotify album id {identifier!r} was not found."
            ) from error
        raise
    if not isinstance(raw, dict):
        raise SpotifyLookupResponseError(
            f"Spotify returned invalid album data for {identifier!r}."
        )
    return lookup_records.live_album(raw, identifier)


def _album_search(
    sp: Spotify, name: str, artist: str | None
) -> list[LiveAlbumCandidate]:
    escaped = name.replace('"', " ").strip()
    query = f'album:"{escaped}"'
    if artist:
        query += f' artist:"{artist.replace(chr(34), " ").strip()}"'
    response = sp.search(q=query, type="album", limit=SPOTIFY_SEARCH_LIMIT, offset=0)
    rows = lookup_records.search_items(
        response, "albums", f"Spotify returned invalid album search data for {name!r}."
    )
    return lookup_records.live_albums(rows)


def _live_liked_statuses(sp: Spotify, ids: list[str]) -> object:
    return sp.current_user_saved_tracks_contains(ids)
