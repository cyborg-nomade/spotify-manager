"""Freeze original paged catalog reads, caches and primary queue membership."""

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.routines import review_artists as legacy
from tests.support.artist_review_run import artist
from tests.support.artist_review_run import clone
from tests.support.artist_review_run import release


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/artist_review_catalog.json"
)
PROFILES = (
    "normal",
    "empty",
    "cached-empty",
    "cached-complete",
    "scan-resume",
    "scan-complete",
    "invalid-cache",
    "duplicate",
    "malformed-first",
    "first-404",
    "first-503",
    "wrong-credit",
    "invalid-page",
    "empty-next",
    "non-studio",
    "paged",
    "invalid-items",
    "invalid-cache-items",
)
KINDS = ("tracks", "ranked", "earliest", "members")


def _raw_track(identity: str, primary: str = "a") -> dict[str, object]:
    return {
        "id": identity,
        "name": identity,
        "uri": f"spotify:track:{identity}",
        "artists": [{"id": primary, "name": primary.upper()}],
        "album": {"name": "Album"},
        "popularity": 0,
    }


def _raw_release(identity: str, year: str = "2000") -> dict[str, object]:
    return {
        "id": identity,
        "name": identity,
        "uri": f"spotify:album:{identity}",
        "artists": [{"id": "a", "name": "A"}],
        "album_type": "album",
        "release_date": year,
        "total_tracks": 10,
    }


def _rows(profile: str, kind: str) -> list[object]:
    if profile in {"empty", "empty-next"}:
        return []
    identities = (
        [str(index) for index in range(31)]
        if profile in {"paged", "search-exhausted", "member-total-only"}
        else ["one", "two"]
    )
    rows: list[object] = []
    for identity in identities:
        rows.append(
            _raw_track(identity)
            if kind in {"track", "members"}
            else _raw_release(identity)
        )
    if profile == "duplicate":
        rows.extend([None, {}, rows[0]])
    if profile == "wrong-credit":
        return (
            [_raw_track("other", "other")]
            if kind in {"track", "members"}
            else [{**_raw_release("other"), "artists": [{"id": "other"}]}]
        )
    if profile == "search-exhausted":
        return _singles(rows)
    if profile == "members-missing-fields":
        return [
            {"id": "", "uri": "", "artists": []},
            {"id": "kept", "artists": [{"id": "a"}]},
        ]
    if profile == "non-studio":
        rows[0] = {
            **cast(dict[str, object], rows[0]),
            "album_type": "single",
            "total_tracks": 2,
        }
    return rows


@dataclass
class CatalogObservations:
    """Record original complete paged reads and accepted cache checkpoints.

    Args:
        profile: Original catalog or failure input.
        trace: Complete original read and checkpoint observations.
        cache: Original mutable metadata record.
    """

    profile: str
    trace: list[list[object]] = field(default_factory=list)
    cache: dict[str, dict[str, object]] = field(default_factory=dict)

    def record(self, name: str, *values: object) -> None:
        """Record original boundary observations with detached accepted values.

        Args:
            name: Original boundary identity.
            values: Complete original arguments or checkpoint values.
        """
        self.trace.append(clone([name, *values]))

    def save(self, path: Path, cache: dict[str, dict[str, object]]) -> None:
        """Observe the original exact metadata checkpoint.

        Args:
            path: Original metadata location.
            cache: Complete original mutable cache.
        """
        self.record("save", str(path), cache)

    def search(self, q: str, limit: int, offset: int, **kwargs: str) -> object:
        """Supply original paged search data.

        Args:
            q: Original exact artist query.
            limit: Original page limit.
            offset: Original raw offset.
            kwargs: Original search type.

        Returns:
            Configured original raw response.
        """
        kind = kwargs["type"]
        self.record("search", q, limit, offset, kwargs)
        page = _page(self.profile, kind, limit, offset)
        return {kind + "s": page} if isinstance(page, dict) else page

    def artist_albums(
        self, identity: str, include_groups: str, limit: int, offset: int
    ) -> object:
        """Supply original raw complete discography pages.

        Args:
            identity: Original artist identity.
            include_groups: Original complete release groups.
            limit: Original raw page limit.
            offset: Original raw offset.

        Returns:
            Configured original raw response.
        """
        self.record("artist-albums", identity, include_groups, limit, offset)
        return _page(self.profile, "album", limit, offset)

    def album_tracks(self, identity: str, limit: int, offset: int) -> object:
        """Supply original first-track data and narrowed failures.

        Args:
            identity: Original release identity.
            limit: Original one-track limit.
            offset: Original zero offset.

        Returns:
            Original first-track page.

        Raises:
            SpotifyException: Original missing or unavailable first-track response.
        """
        self.record("first", identity, limit, offset)
        if self.profile in {"first-404", "first-503"}:
            raise SpotifyException(int(self.profile[-3:]), -1, "original first failure")
        if self.profile == "malformed-first":
            return {"items": None}
        if self.profile == "first-empty-row":
            return {"items": [None]}
        primary = "other" if self.profile == "wrong-credit" else "a"
        return {"items": [_raw_track(identity + "-first", primary)]}

    def _get(self, path: str, limit: int, offset: int) -> object:
        self.record("get", path, limit, offset)
        page_limit = 10 if self.profile == "member-total-only" else limit
        page = _page(self.profile, "members", page_limit, offset)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            return page
        page["items"] = [{"item": item} for item in page["items"]]
        if self.profile == "members-alternate":
            page["items"] = [
                None,
                {},
                {"track": _raw_track("alternate")},
                {"item": False, "track": _raw_track("fallback")},
            ]
        if self.profile == "member-total-only":
            page["next"] = None
        if self.profile == "members-no-total":
            page["total"] = None
        return page


def _page(profile: str, kind: str, limit: int, offset: int) -> object:
    if profile == "invalid-page":
        return []
    if profile == "invalid-items":
        return {"items": None}
    rows = _rows(profile, kind)
    items = rows[offset : offset + limit]
    return {
        "items": items,
        "total": len(rows),
        "next": "next"
        if offset + len(items) < len(rows) or profile == "empty-next"
        else None,
    }


def _prepare_cache(edge: CatalogObservations, kind: str) -> None:
    key = (
        "ranked_tracks"
        if kind == "tracks"
        else "earliest_releases"
        if kind == "earliest"
        else "ranked_releases"
    )
    values: dict[str, object] = {}
    if edge.profile == "cached-empty":
        values[key] = []
    if edge.profile == "cached-complete" and kind != "tracks":
        values[key] = [asdict(release("a"))]
    if edge.profile == "invalid-cache":
        values[key] = [{"unknown": "value"}]
    if edge.profile.startswith("scan") or edge.profile == "invalid-cache-items":
        values["discography_scan"] = {
            "offset": 1,
            "complete": edge.profile == "scan-complete",
            "items": [_raw_release("past", "1900")],
        }
    if edge.profile == "invalid-cache-items":
        scan = cast(dict[str, object], values["discography_scan"])
        scan["items"] = "invalid"
    edge.cache["a"] = values
    if edge.profile == "invalid-scan":
        values["discography_scan"] = "invalid"


def _retry(
    edge: CatalogObservations, operation: Callable[[], object], description: str
) -> object:
    edge.record("retry", description)
    return operation()


def outcome(profile: str, kind: str, repeat: bool = False) -> dict[str, object]:
    """Observe original catalog results, complete requests and every checkpoint.

    Args:
        profile: Original raw catalog or failure input.
        kind: Original catalog or membership operation.
        repeat: Whether to replay through the accepted metadata cache.

    Returns:
        Complete deterministic original results, reads and cache observations.
    """
    edge = CatalogObservations(profile)
    _prepare_cache(edge, kind)
    results: list[object] = []
    with patch.object(legacy, "save_cache", edge.save):
        for _attempt in range(2 if repeat else 1):
            _observe(edge, kind, results)
    return clone({"results": results, "trace": edge.trace, "cache": edge.cache})


def _observe(edge: CatalogObservations, kind: str, results: list[object]) -> None:
    try:
        result = _invoke(edge, kind)
        results.append({"value": result})
    except (
        RuntimeError,
        TypeError,
        ValueError,
        AssertionError,
        SpotifyException,
    ) as exc:
        results.append({"error": type(exc).__name__, "message": str(exc)})


def _invoke(edge: CatalogObservations, kind: str) -> object:
    retry = partial(_retry, edge)
    spotify = cast(Spotify, edge)
    if kind == "members":
        membership = legacy.playlist_membership(spotify, "one", retry)
        return {
            "primary_artist_ids": sorted(membership.primary_artist_ids),
            "track_ids": sorted(membership.track_ids),
            "track_uris_by_primary_artist": membership.track_uris_by_primary_artist,
        }
    operation = _operation(kind)
    result = operation(
        spotify, artist("a"), edge.cache, Path("/original/cache.json"), retry
    )
    return [asdict(item) for item in result]


def cases() -> list[dict[str, object]]:
    """Read immutable complete original catalog observations.

    Returns:
        Original scenario inputs, results, reads and accepted checkpoints.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))


def _operation(
    kind: str,
) -> Callable[
    [Spotify, YourLibraryArtist, dict[str, dict[str, object]], Path, legacy.RetryCall],
    list[legacy.TrackCandidate] | list[legacy.ReleaseCandidate],
]:
    if kind == "tracks":
        return legacy.ranked_artist_tracks
    if kind == "ranked":
        return legacy.ranked_artist_releases
    return legacy.earliest_artist_releases


def _singles(rows: list[object]) -> list[object]:
    singles: list[object] = []
    for row in rows:
        singles.append(
            {**cast(dict[str, object], row), "album_type": "single", "total_tracks": 2}
        )
    return singles
