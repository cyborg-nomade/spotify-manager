"""Pure Palace mirror positions, preferred saved editions and live classification."""

from dataclasses import replace
from typing import Protocol

from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history_matching import name_similarity
from spotify_manager.domain.palace_values import CatalogAlbum
from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.domain.palace_values import SelectionAction
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack


class AlbumFacts(Protocol):
    """Original saved-album identity and display facts without boundary models."""

    @property
    def artist(self) -> str:
        """Read original artist display spelling.

        Returns:
            Original artist name.
        """

    @property
    def album(self) -> str:
        """Read original saved title.

        Returns:
            Original album title.
        """

    @property
    def uri(self) -> str:
        """Read original saved reference.

        Returns:
            Original Spotify album reference.
        """

    @property
    def spotify_id(self) -> str:
        """Read the original mirror identity.

        Returns:
            Original Spotify album identity.
        """
        ...


def alphabetical[T: AlbumFacts](
    albums: tuple[T, ...], start: int, count: int = 5
) -> tuple[T, ...]:
    """Select the original consecutive saved albums, wrapping through the mirror.

    Args:
        albums: Original canonical ordered mirror.
        start: Original starting index, including supported negative positions.
        count: Original number of distinct mirror positions to select.

    Returns:
        Original complete facts in selected order.

    Raises:
        ValueError: The original count cannot fit within the mirror.
    """
    if count < 1 or count > len(albums):
        raise ValueError("count must fit within the saved album mirror")
    result = []
    for offset in range(count):
        result.append(albums[(start + offset) % len(albums)])
    return tuple(result)


def cursor_index(
    albums: tuple[AlbumFacts, ...], last_identity: str, fallback: int
) -> int:
    """Prefer the original last-album identity over a wrapped fallback position.

    Args:
        albums: Current canonical mirror order.
        last_identity: Original last successfully selected saved identity.
        fallback: Validated original fallback index.

    Returns:
        Original next zero-based position in the current mirror.

    Raises:
        ZeroDivisionError: The original mirror is empty.
    """
    if not last_identity:
        return fallback % len(albums)
    for index, album in enumerate(albums):
        if album.spotify_id == last_identity:
            return (index + 1) % len(albums)
    return fallback % len(albums)


def preferred_saved(
    artist: str, album: str, saved: tuple[AlbumFacts, ...], threshold: float = 0.9
) -> SpotifyAlbum | None:
    """Prefer the original best qualified saved edition, retaining first ties.

    Args:
        artist: Original expected artist spelling.
        album: Original expected album title.
        saved: Original current saved-album mirror.
        threshold: Original album qualification threshold.

    Returns:
        Original preferred saved edition or none.
    """
    expected = normalize_name(artist)
    candidates = []
    for item in saved:
        if normalize_name(item.artist) != expected:
            continue
        similarity = name_similarity(album, item.album)
        if similarity >= threshold:
            candidates.append(
                SpotifyAlbum(
                    item.spotify_id, item.uri, item.artist, item.album, True, similarity
                )
            )
    return max(candidates, key=_similarity, default=None)


def _similarity(album: SpotifyAlbum) -> float:
    return album.similarity


def preferred_catalog(
    artist: str,
    album: str,
    observed: tuple[CatalogAlbum, ...],
    threshold: float = 0.9,
) -> SpotifyAlbum | None:
    """Select original exact-artist catalog editions by similarity then search rank.

    Args:
        artist: Original expected artist spelling.
        album: Original expected historical title.
        observed: Complete original catalog rows in search order.
        threshold: Original album-title qualification threshold.

    Returns:
        Original preferred qualified release with its first credited display name.
    """
    expected = normalize_name(artist)
    matches = []
    for candidate in observed:
        if not any(normalize_name(name) == expected for name in candidate.artists):
            continue
        similarity = name_similarity(album, candidate.name)
        if similarity < threshold:
            continue
        selected = SpotifyAlbum(
            candidate.spotify_id,
            candidate.uri,
            candidate.artists[0],
            candidate.name,
            False,
            similarity,
        )
        matches.append((candidate.rank, selected))
    if not matches:
        return None
    return max(matches, key=_catalog_rank)[1]


def _catalog_rank(item: tuple[int, SpotifyAlbum]) -> tuple[float, int]:
    return item[1].similarity, -item[0]


def classify(
    planned: list[PalaceAlbumResult], current_ids: frozenset[str]
) -> tuple[tuple[PalaceAlbumResult, ...], tuple[SpotifyFirstTrack, ...]]:
    """Classify original first markers against live and pending identities.

    Args:
        planned: Original ordered alphabetical and historical proposals.
        current_ids: Original latest observed playlist membership.

    Returns:
        Original ordered outcomes and first distinct pending markers.
    """
    results = []
    pending = []
    pending_ids: set[str] = set()
    for result in planned:
        action = _action(result, current_ids, pending_ids)
        if action == "added" and result.first_track is not None:
            pending_ids.add(result.first_track.spotify_id)
            pending.append(result.first_track)
        results.append(replace(result, action=action))
    return tuple(results), tuple(pending)


def _action(
    result: PalaceAlbumResult, current: frozenset[str], pending: set[str]
) -> SelectionAction:
    track = result.first_track
    if result.spotify_album is None or track is None:
        return "no match"
    if track.spotify_id in current:
        return "already present"
    if track.spotify_id in pending:
        return "duplicate selection"
    return "added"
