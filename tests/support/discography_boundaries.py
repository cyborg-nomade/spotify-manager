"""Observe original Discography catalog, history and ordered queue boundaries."""

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import discography as legacy
from spotify_manager.routines import new_wine
from tests.support.discography_run import FIXTURE
from tests.support.palace_history import HistoryReads


def raw_release(identity: str, name: str = "Studio") -> dict[str, object]:
    """Build complete original raw catalog input.

    Args:
        identity: Original release identity.
        name: Original display title.

    Returns:
        Complete Spotify boundary fields.
    """
    return {
        "id": identity,
        "uri": f"spotify:album:{identity}",
        "name": name,
        "release_date": "2020",
        "album_type": "album",
        "total_tracks": 10,
        "artists": [{"id": "artist", "name": "Artist"}],
    }


def raw_cases() -> list[object]:
    """Enumerate original permissive parsing and release qualification boundaries.

    Returns:
        Complete raw records captured before migration.
    """
    rows: list[object] = [None, [], {}, raw_release("studio")]
    changes = {
        "id": (None, "", 5, " "),
        "uri": (None, "", " "),
        "name": (None, "", " ", "Live!", "Best Of", "Unknown EP"),
        "album_type": ("single", "ep", "compilation", "OTHER", " album"),
        "album_group": ("compilation", " compilation"),
        "total_tracks": (True, False, "5", 0, -1, 4),
        "artists": (
            None,
            [],
            [{"id": "other"}],
            [{"id": "artist"}],
            [None, {"id": "artist", "name": 5}],
        ),
        "release_date": (None, "", "unknown", " 2021", 5),
    }
    for key, values in changes.items():
        for value in values:
            rows.append(raw_release("record") | {key: value})
    for total in (True, "5", 3, 4):
        rows.append(
            raw_release("single") | {"album_type": "single", "total_tracks": total}
        )
    return rows


@dataclass
class CatalogReads:
    """Observe original pagination and saved-status batch authority.

    Args:
        profile: Configured original malformed or complete pages.
        trace: Complete ordered boundary observations.
    """

    profile: str
    trace: list[list[object]] = field(default_factory=list)

    def artist_albums(
        self,
        artist: str,
        *,
        include_groups: str,
        limit: int,
        offset: int,
    ) -> object:
        """Supply original raw pages.

        Args:
            artist: Original primary identity.
            include_groups: Original requested release groups.
            limit: Original page size.
            offset: Original raw-row offset.

        Returns:
            Original complete or invalid page.
        """
        self.trace.append(["page", artist, include_groups, limit, offset])
        if self.profile == "invalid":
            return None
        if self.profile == "bad-items":
            return {"items": (), "next": None}
        if self.profile == "empty-next":
            return {"items": [], "next": "next"}
        rows = _catalog_rows(self.profile)
        page = rows[offset : offset + limit]
        return {
            "items": page,
            "next": "next" if offset + len(page) < len(rows) else None,
        }

    def current_user_saved_albums_contains(self, identities: list[str]) -> object:
        """Supply original tolerant saved-status values.

        Args:
            identities: Original ordered batch.

        Returns:
            Original matching or malformed status list.
        """
        self.trace.append(["saved", identities])
        if self.profile == "bad-status":
            return None
        if self.profile == "short-status":
            return []
        statuses = []
        for identity in identities:
            statuses.append(identity == "decorated" or self.profile == "truthy")
        return statuses

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Observe original retry placement.

        Args:
            operation: Original deferred SDK call.
            description: Original retry description.

        Returns:
            Original SDK result.
        """
        self.trace.append(["retry", description])
        return operation()


def _catalog_rows(profile: str) -> list[object]:
    if profile == "empty":
        return []
    if profile == "large":
        return [raw_release(f"id-{index}", f"Release {index}") for index in range(43)]
    return [
        raw_release("plain", "Original") | {"release_date": "2010"},
        raw_release("decorated", "Original (Deluxe Edition)")
        | {"release_date": "2020"},
        raw_release("live", "Live!"),
        raw_release("comp", "Best Of"),
        raw_release("single") | {"album_type": "single", "total_tracks": 1},
        None,
        raw_release("plain", "Original") | {"release_date": "2011"},
    ]


def catalog_outcome(profile: str) -> object:
    """Capture original complete catalog and failure prefixes.

    Args:
        profile: Original raw boundary behavior.

    Returns:
        Complete original parsed facts and ordered calls.
    """
    edge = CatalogReads(profile)
    result: dict[str, object] = {}
    try:
        releases = legacy.load_release_catalog(
            cast(Spotify, edge), "artist", edge.retry
        )
        result["result"] = [asdict(item) for item in releases]
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return result


def history_outcome(profile: str, second: int) -> object:
    """Capture original history, cutoff, random and seconds behavior.

    Args:
        profile: Original configured reader behavior.
        second: Original selection second.

    Returns:
        Complete original result or failure and ordered reads.
    """
    edge = HistoryReads(profile, second)
    result: dict[str, object] = {}
    try:
        result["result"] = _historical(edge)
    except (RuntimeError, IndexError) as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


def _historical(edge: HistoryReads) -> object:
    with patch.object(blast_from_past, "load_scrobbles_by_date", edge.read):
        selected = legacy.select_historical_artist(
            path=FIXTURE.with_name("history"),
            today=date(2026, 8, 8),
            random_index_reader=edge.random,
            progress_callback=edge.progress,
        )
    return asdict(selected)


def marker(identity: str, artist: str, name: str) -> PlaylistTrack:
    """Build original complete primary marker facts.

    Args:
        identity: Original marker URI.
        artist: Original primary identity.
        name: Original display spelling.

    Returns:
        Original complete playable marker.
    """
    album = ReleaseCandidate("album", "uri", "Album", "Album", "2020", 10, artist, name)
    return PlaylistTrack(identity, identity, identity, artist, name, album)


@dataclass
class QueueReads:
    """Observe original queue candidate and auxiliary marker gathering.

    Args:
        failure: Optional playlist whose original read fails.
        trace: Original ordered playlist reads.
    """

    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)

    def read(
        self, spotify: Spotify, playlist: str, retry: legacy.RetryCall
    ) -> tuple[PlaylistTrack, ...]:
        """Supply original duplicate markers and changing artist display names.

        Args:
            spotify: Original SDK boundary.
            playlist: Original source identity.
            retry: Original caller retry.

        Returns:
            Original complete raw-order marker facts.

        Raises:
            NewWineError: The configured original playlist fails.
        """
        self.trace.append(["playlist", playlist])
        if playlist == self.failure:
            raise new_wine.NewWineError("playlist failed")
        return (
            marker("first", "a", "Alpha"),
            marker("second", "b", "Beta"),
            marker("first", "a", "Changed"),
            marker("third", "a", "Changed"),
        )


def queue_outcome(extra: str | None, failure: str | None) -> object:
    """Capture original complete queue and marker grouping.

    Args:
        extra: Original optional auxiliary playlist, including empty strings.
        failure: Original read failure location.

    Returns:
        Complete original groups or failure prefix.
    """
    edge = QueueReads(failure)
    result: dict[str, object] = {}
    try:
        result["result"] = _queues(edge, extra)
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result))


def _queues(edge: QueueReads, extra: str | None) -> object:
    with patch.object(new_wine, "load_playlist_tracks", edge.read):
        queues, groups = legacy._load_artist_queues(
            cast(Spotify, edge),
            {"newfoundland": "nf", "memory_lane": "ml", "requeue": "rq"},
            cast(legacy.RetryCall, None),
            extra,
        )
    queue_rows = {
        name: [asdict(item) for item in items] for name, items in queues.items()
    }
    group_rows = {
        name: [asdict(item) for item in items] for name, items in groups.items()
    }
    return {"queues": queue_rows, "markers": group_rows}
