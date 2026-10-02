"""Compare independently injected catalog gathering with complete original traces."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import cast

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application.artist_review_catalog import ArtistCatalog
from spotify_manager.application.artist_review_catalog import CatalogScan
from spotify_manager.application.artist_review_catalog import FirstTrack
from spotify_manager.application.artist_review_catalog import RawReleasePage
from spotify_manager.application.artist_review_catalog import ReleasePage
from spotify_manager.application.artist_review_membership import MembershipPage
from spotify_manager.application.artist_review_membership import QueueMarker
from spotify_manager.application.artist_review_membership import playlist_membership
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from tests.support import artist_review_catalog as original
from tests.support.artist_review_run import clone


Raw = dict[str, object]
CACHE_PATH = Path("/original/cache.json")


@dataclass(frozen=True)
class MemoryCatalog:
    """Supply original accepted catalog authority without production adapters.

    Args:
        edge: Original raw test facts, reads and accepted checkpoints.
    """

    edge: original.CatalogObservations

    def tracks(self) -> list[TrackCandidate] | None:
        """Decode the original fixture cache at the injected boundary.

        Returns:
            Complete observed candidate list or None for a miss.
        """
        raw = self.edge.cache["a"].get("ranked_tracks")
        if not isinstance(raw, list):
            return None
        return [_cached_track(item) for item in raw]

    def releases(self, key: str) -> list[ReleaseCandidate] | None:
        """Decode the original fixture release cache at the injected boundary.

        Args:
            key: Original catalog namespace.

        Returns:
            Original complete candidate list or None for a miss.
        """
        raw = self.edge.cache["a"].get(key)
        if not isinstance(raw, list):
            return None
        return [_cached_release(item) for item in raw]

    def save_tracks(self, tracks: list[TrackCandidate]) -> None:
        """Accept and observe the original complete ranked-track checkpoint.

        Args:
            tracks: Original complete qualified track list.
        """
        self.edge.cache["a"]["ranked_tracks"] = [asdict(item) for item in tracks]
        self.edge.save(CACHE_PATH, self.edge.cache)

    def save_releases(self, key: str, releases: list[ReleaseCandidate]) -> None:
        """Accept and observe the original complete release checkpoint.

        Args:
            key: Original catalog namespace.
            releases: Original complete mutable release list.
        """
        self.edge.cache["a"][key] = [asdict(item) for item in releases]
        self.edge.save(CACHE_PATH, self.edge.cache)

    def scan(self) -> CatalogScan:
        """Resolve the observed raw scan with its original shape guard.

        Returns:
            Original mutable fixture scan.

        Raises:
            ArtistReviewError: Original scan is not a dictionary.
        """
        raw = self.edge.cache["a"].setdefault(
            "discography_scan", {"offset": 0, "complete": False, "items": []}
        )
        if not isinstance(raw, dict):
            raise ArtistReviewError("Invalid cached discography for A.")
        return MemoryScan(self.edge, raw)

    def read_tracks(self) -> list[TrackCandidate]:
        """Supply observed parsed ranked tracks at the injected read boundary.

        Returns:
            Complete original associated tracks.
        """
        self.edge.record("retry", "searching ranked tracks for A")
        response = self.edge.search('artist:"A"', 10, 0, type="track")
        page = _search_page(response, "tracks")
        tracks = []
        for rank, row in enumerate(cast(list[object], page["items"]), start=1):
            track = _parsed_track(row, rank)
            if track is not None:
                tracks.append(track)
        return tracks

    def read_search(self, offset: int) -> ReleasePage:
        """Supply observed parsed release pages with original raw accounting.

        Args:
            offset: Original raw request offset.

        Returns:
            Original complete associated release facts and raw accounting.
        """
        self.edge.record("retry", f"searching ranked releases for A at offset {offset}")
        response = self.edge.search('artist:"A"', 10, offset, type="album")
        page = _search_page(response, "albums")
        rows = cast(list[object], page["items"])
        return ReleasePage(
            tuple(_parsed_releases(rows, offset)), len(rows), bool(page.get("next"))
        )

    def read_discography(self, offset: int) -> RawReleasePage:
        """Supply observed complete raw discography pages for durable staging.

        Args:
            offset: Original raw request offset.

        Returns:
            Original complete raw rows and next authority.
        """
        self.edge.record("retry", f"fetching releases for A at offset {offset}")
        response = self.edge.artist_albums("a", "album,single,compilation", 10, offset)
        page = _page(response, "Spotify returned invalid release data for A.")
        return RawReleasePage(
            tuple(cast(list[object], page["items"])), bool(page.get("next"))
        )

    def read_first(self, release: ReleaseCandidate) -> FirstTrack | None:
        """Supply observed first markers with original narrowed 404 handling.

        Args:
            release: Original displayed release.

        Returns:
            Original complete first marker or None after an empty/404 result.
        """
        self.edge.record("retry", f"fetching the first track of {release.name}")
        try:
            raw = self.edge.album_tracks(release.spotify_id, 1, 0)
        except SpotifyException as exc:
            if exc.http_status != 404:
                raise
            raw = {"items": []}
        page = _page(
            raw, f"Spotify returned invalid first-track data for {release.name}."
        )
        rows = cast(list[object], page["items"])
        if not rows or not isinstance(rows[0], dict):
            return None
        first = cast(Raw, rows[0])
        artists = cast(list[Raw], first["artists"])
        return FirstTrack(
            cast(str, first["id"]),
            cast(str, first["name"]),
            cast(str, first["uri"]),
            cast(str, artists[0]["id"]),
            cast(str, artists[0]["name"]),
        )

    def read_membership(self, offset: int) -> MembershipPage:
        """Supply observed parsed queue facts at the injected raw-page boundary.

        Args:
            offset: Original complete raw request offset.

        Returns:
            Original complete independent marker facts and pagination authority.
        """
        self.edge.record("retry", f"loading queue playlist one at offset {offset}")
        raw = self.edge._get("playlists/one/items", 50, offset)
        page = _page(raw, "Spotify returned invalid playlist data for one.")
        rows = cast(list[object], page["items"])
        markers = []
        for row in rows:
            marker = _entry_marker(row)
            if marker is not None:
                markers.append(marker)
        total = page.get("total")
        return MembershipPage(
            tuple(markers),
            len(rows),
            bool(page.get("next")),
            total if isinstance(total, int) else None,
        )


@dataclass(frozen=True)
class MemoryScan:
    """Retain independent accepted raw scan authority in the test boundary.

    Args:
        edge: Original observed complete cache.
        raw: Original mutable raw scan.
    """

    edge: original.CatalogObservations
    raw: Raw

    def complete(self) -> bool:
        """Read original completion.

        Returns:
            Original stored completion truthiness.
        """
        return bool(self.raw.get("complete"))

    def offset(self) -> int:
        """Read original raw offset.

        Returns:
            Original effective integer offset.
        """
        return int(cast(int, self.raw.get("offset", 0)))

    def accept(self, page: RawReleasePage, offset: int) -> None:
        """Accept original raw page progress before checkpointing.

        Args:
            page: Original complete raw page.
            offset: Original effective request offset.
        """
        items = self.raw.setdefault("items", [])
        if not isinstance(items, list):
            raise ArtistReviewError("Invalid cached discography for A.")
        items.extend(page.rows)
        self.raw["offset"] = offset + len(page.rows)
        self.raw["complete"] = not page.has_next
        if not page.rows and page.has_next:
            raise ArtistReviewError("Spotify returned an empty release page for A.")
        self.edge.save(CACHE_PATH, self.edge.cache)

    def candidates(self) -> list[ReleaseCandidate]:
        """Supply original delayed associated release facts.

        Returns:
            Original complete raw-rank candidates.
        """
        raw = self.raw.get("items", [])
        assert isinstance(raw, list)
        return _parsed_releases(raw, 0)


def _cached_track(raw: object) -> TrackCandidate:
    # The original fixture deliberately tests permissive JSON constructor errors.
    return TrackCandidate(**cast(dict[str, Any], raw))


def _cached_release(raw: object) -> ReleaseCandidate:
    # The original fixture deliberately tests permissive JSON constructor errors.
    return ReleaseCandidate(**cast(dict[str, Any], raw))


def _search_page(raw: object, kind: str) -> Raw:
    label = "track" if kind == "tracks" else "release"
    message = f"Spotify returned invalid {label} search for A."
    if not isinstance(raw, dict):
        raise ArtistReviewError(message)
    return _page(raw.get(kind), message)


def _page(raw: object, message: str) -> Raw:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ArtistReviewError(message)
    return raw


def _associated(raw: object) -> bool:
    if not isinstance(raw, dict) or not raw.get("id") or not raw.get("uri"):
        return False
    artists = raw.get("artists")
    if not isinstance(artists, list):
        return False
    return any(
        isinstance(artist, dict) and artist.get("id") == "a" for artist in artists
    )


def _parsed_track(raw: object, rank: int) -> TrackCandidate | None:
    if not _associated(raw):
        return None
    row = cast(Raw, raw)
    artists = cast(list[Raw], row["artists"])
    identities = tuple(cast(str, item["id"]) for item in artists)
    album = cast(Raw, row["album"])
    return TrackCandidate(
        cast(str, row["id"]),
        cast(str, row["name"]),
        cast(str, row["uri"]),
        cast(str, album["name"]),
        rank,
        identities[0],
        cast(str, artists[0]["name"]),
        identities,
        cast(int, row["popularity"]),
    )


def _parsed_releases(rows: list[object], offset: int) -> list[ReleaseCandidate]:
    releases = []
    for index, raw in enumerate(rows, start=1):
        if _associated(raw):
            releases.append(_parsed_release(cast(Raw, raw), offset + index))
    return releases


def _parsed_release(row: Raw, rank: int) -> ReleaseCandidate:
    artists = cast(list[Raw], row["artists"])
    identities = tuple(cast(str, item["id"]) for item in artists)
    kind = "Single" if row["album_type"] == "single" else "Album"
    return ReleaseCandidate(
        cast(str, row["id"]),
        cast(str, row["name"]),
        cast(str, row["uri"]),
        kind,
        cast(str, row["release_date"]),
        cast(int, row["total_tracks"]),
        rank,
        identities[0],
        cast(str, artists[0]["name"]),
        identities,
    )


def _parsed_marker(raw: object) -> QueueMarker | None:
    if not isinstance(raw, dict):
        return None
    artists = cast(list[Raw], raw.get("artists", []))
    primary = cast(str, artists[0]["id"]) if artists else None
    return QueueMarker(
        str(raw.get("id") or "").strip(), primary, str(raw.get("uri") or "").strip()
    )


def _entry_marker(raw: object) -> QueueMarker | None:
    if not isinstance(raw, dict):
        return None
    return _parsed_marker(raw.get("item") or raw.get("track"))


def _invoke(edge: original.CatalogObservations, kind: str) -> object:
    memory = MemoryCatalog(edge)
    if kind == "members":
        result = playlist_membership("one", memory.read_membership)
        return {
            "primary_artist_ids": sorted(result.primary_artist_ids),
            "track_ids": sorted(result.track_ids),
            "track_uris_by_primary_artist": result.track_uris_by_primary_artist,
        }
    catalog = ArtistCatalog(
        memory,
        memory.read_tracks,
        memory.read_search,
        memory.read_discography,
        memory.read_first,
    )
    operations: dict[
        str, Callable[[], list[TrackCandidate] | list[ReleaseCandidate]]
    ] = {
        "tracks": catalog.ranked_tracks,
        "ranked": catalog.ranked_releases,
        "earliest": catalog.earliest_releases,
    }
    return [asdict(item) for item in operations[kind]()]


def _outcome(case: Raw) -> Raw:
    edge = original.CatalogObservations(cast(str, case["profile"]))
    original._prepare_cache(edge, cast(str, case["kind"]))
    results: list[object] = []
    for _attempt in range(2 if case["repeat"] else 1):
        _observe(edge, cast(str, case["kind"]), results)
    return clone({"results": results, "trace": edge.trace, "cache": edge.cache})


def _observe(
    edge: original.CatalogObservations, kind: str, results: list[object]
) -> None:
    try:
        results.append({"value": _invoke(edge, kind)})
    except (
        RuntimeError,
        TypeError,
        ValueError,
        AssertionError,
        SpotifyException,
    ) as exc:
        results.append({"error": type(exc).__name__, "message": str(exc)})


@pytest.mark.parametrize("case", original.cases())
def test_injected_catalog_matches_original_complete_effects(case: Raw) -> None:
    """Retain every catalog read, raw offset, delayed scan and accepted checkpoint.

    Args:
        case: Immutable original complete catalog scenario and observations.
    """
    assert _outcome(case) == case["outcome"]


@pytest.mark.parametrize("case", original.cases())
def test_public_catalog_matches_original_complete_effects(case: Raw) -> None:
    """Verify original compatibility entry points bind unchanged complete reads.

    Args:
        case: Immutable original complete catalog scenario and observations.
    """
    assert (
        original.outcome(
            cast(str, case["profile"]),
            cast(str, case["kind"]),
            cast(bool, case["repeat"]),
        )
        == case["outcome"]
    )
