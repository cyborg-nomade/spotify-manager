"""Freeze original live/local lookup observations before structural migration."""

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast

import pytest
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.processors import library_lookups as library
from spotify_manager.processors import scrobble_lookups as scrobbles
from spotify_manager.routines import blast_from_past
from tests.support.effects import Json
from tests.support.effects import encode_value


@dataclass(frozen=True)
class LookupScenario:
    """Select one original lookup and its raw response profile.

    Args:
        workflow: Original public lookup.
        profile: Original raw response boundary.
    """

    workflow: str
    profile: str


def lookup_scenarios() -> list[LookupScenario]:
    """Enumerate immutable public lookup and cache scenarios.

    Returns:
        Original scenario matrix.
    """
    workflows = (
        "artist-id",
        "artist-name",
        "artist-stats",
        "album-id",
        "album-name",
        "local-album",
        "local-evaluate",
        "tracklist",
        "track-id",
        "track-name",
        "track-status",
    )
    profiles = (
        "normal",
        "empty",
        "duplicate",
        "ambiguous",
        "invalid",
        "null",
        "empty-next",
        "bad-page",
        "short-status",
        "truthy-status",
        "edition",
        "404",
        "403",
        "500",
        "cache-hit",
        "cache-empty",
        "cache-invalid",
        "cache-save-failure",
        "many",
        "bad-history",
        "bad-time",
        "ignored-bad-time",
        "out-of-range",
    )
    result = []
    for workflow in workflows:
        for profile in profiles:
            result.append(LookupScenario(workflow, profile))
    return result


def raw_album(
    identifier: str, name: str = "Album", artist: str = "Artist"
) -> dict[str, object]:
    """Raw album.

    Args:
        identifier: Original requested identity.
        name: Original optional exact display name.
        artist: Original optional primary artist constraint.

    Returns:
        Original raw album result.
    """
    return {
        "id": identifier,
        "name": name,
        "artists": [{"id": "artist", "name": artist}],
    }


def raw_track(
    identifier: str, name: str = "Track", artist: str = "Artist", popularity: int = 50
) -> dict[str, object]:
    """Raw track.

    Args:
        identifier: Original requested identity.
        name: Original optional exact display name.
        artist: Original optional primary artist constraint.
        popularity: Original integer popularity used only for representative selection.

    Returns:
        Original raw track result.
    """
    return {
        "id": identifier,
        "name": name,
        "uri": f"spotify:track:{identifier}",
        "artists": [{"id": "artist", "name": artist}],
        "album": {"name": "Album"},
        "popularity": popularity,
    }


class LookupMemory:
    """Record original reads, SDK responses and accepted cache publications.

    Args:
        scenario: Selected original boundary profile.
    """

    def __init__(self, scenario: LookupScenario) -> None:
        """init  .

        Args:
            scenario: Selected original workflow and raw response profile.
        """
        self.scenario = scenario
        self.events: list[object] = []
        self.cache: dict[str, Any] = {}
        self.saved_cache: object = None
        self.export = YourLibraryFile(
            albums=[
                YourLibraryAlbum(
                    artist="Artist", album="Album", uri="spotify:album:album"
                )
            ],
            artists=[],
            tracks=[
                YourLibraryTrack(
                    artist="Artist",
                    album="Album",
                    track="Track",
                    uri="spotify:track:track",
                )
            ],
        )
        self.configure()

    def configure(self) -> None:
        profile = self.scenario.profile
        if profile == "empty":
            self.export.albums.clear()
            self.export.tracks.clear()
        if profile == "ambiguous":
            self.export.albums.append(
                YourLibraryAlbum(
                    artist="Other", album="Album", uri="spotify:album:other"
                )
            )
        if profile == "duplicate":
            self.export.albums.extend(self.export.albums.copy())
        if profile == "cache-hit":
            self.cache["album"] = [{"id": "track", "name": "Cached", "uri": "cached"}]
        if profile == "cache-empty":
            self.cache["album"] = []
        if profile == "cache-invalid":
            self.cache["album"] = [{"name": "Broken"}]

    def read_library(self) -> YourLibraryFile:
        """Read original synthetic export facts."""
        self.events.append(["library", self.export.model_dump()])
        return self.export

    def read_cache(self) -> dict[str, Any]:
        """Read original unchecked cache authority."""
        self.events.append(["cache-read", copy.deepcopy(self.cache)])
        return self.cache

    def save_cache(self, value: dict[str, Any]) -> None:
        """Accept original cache bytes before an optional callback failure.

        Args:
            value: Original complete cache authority.

        Raises:
            RuntimeError: The selected original publication is interrupted.
        """
        self.events.append(["cache-save", copy.deepcopy(value)])
        if self.scenario.profile == "cache-save-failure":
            raise RuntimeError("cache publication failed")
        self.saved_cache = copy.deepcopy(value)

    def history(self, path: Path) -> dict[str, object]:
        """Read unchecked history rows with original timestamp boundaries.

        Args:
            path: Original caller-supplied history location.

        Returns:
            Original raw export rows.
        """
        self.events.append(["history", path.name])
        rows: list[object] = [
            {"artist": "Other", "track": "Track", "date": "bad"},
            {"artist": "Artist", "track": "Other", "date": "bad"},
            {"artist": "Artist", "track": "Track", "date": 1000},
            {"artist": "Artist", "track": "Track - Remaster", "date": 2000},
        ]
        profile = self.scenario.profile
        if profile == "empty":
            rows = []
        if profile == "bad-history":
            rows = [None]
        if profile == "bad-time":
            rows = [{"artist": "Artist", "track": "Track", "date": "bad"}]
        if profile == "out-of-range":
            rows = [{"artist": "Artist", "track": "Track", "date": 10**30}]
        return {"scrobbles": rows}

    def respond(self, operation: str, arguments: object, value: object) -> Any:
        """Record original requests and selected malformed responses.

        Args:
            operation: Original SDK method.
            arguments: Original complete request parameters.
            value: Original normal response.

        Returns:
            Original permissive SDK response.

        Raises:
            SpotifyException: The selected original status fails the read.
        """
        self.events.append([operation, copy.deepcopy(arguments)])
        profile = self.scenario.profile
        if profile in ("404", "403", "500"):
            raise SpotifyException(int(profile), -1, "scripted")
        if profile == "null":
            return None
        if profile == "invalid":
            return {"unexpected": True}
        return copy.deepcopy(value)


class LookupCatalog:
    """Supply original raw Spotify responses with complete request recording.

    Args:
        memory: Original mutable observation authority.
    """

    def __init__(self, memory: LookupMemory) -> None:
        """init  .

        Args:
            memory: Recorded original mutable boundary observations.
        """
        self.memory = memory

    def artist(self, identifier: str) -> Any:
        """Read one original artist identity.

        Args:
            identifier: Original requested identity.

        Returns:
            Original artist result.
        """
        return self.memory.respond(
            "artist", identifier, {"id": identifier, "name": "Artist"}
        )

    def album(self, identifier: str) -> Any:
        """Read one original album identity.

        Args:
            identifier: Original requested identity.

        Returns:
            Original album result.
        """
        return self.memory.respond("album", identifier, raw_album(identifier))

    def track(self, identifier: str) -> Any:
        """Read one original track identity.

        Args:
            identifier: Original requested identity.

        Returns:
            Original track result.
        """
        return self.memory.respond("track", identifier, raw_track(identifier))

    def search(self, **parameters: object) -> Any:
        """Read original exact-search inputs and ordered raw candidates."""
        kind = str(parameters["type"])
        items = self.search_items(kind)
        return self.memory.respond("search", parameters, {kind + "s": {"items": items}})

    def search_items(self, kind: str) -> list[object]:
        """Search items.

        Args:
            kind: Original required search resource.

        Returns:
            Original search items result.
        """
        if kind == "artist":
            items: list[object] = [{"id": "artist", "name": "Artist"}]
        elif kind == "album":
            items = [raw_album("album")]
        else:
            items = [raw_track("track")]
        profile = self.memory.scenario.profile
        if profile == "empty":
            return []
        if profile == "duplicate":
            return items + copy.deepcopy(items)
        if profile == "ambiguous":
            return items + ambiguous_item(kind)
        if profile == "edition" and kind == "track":
            return [raw_track("edition", "Track - Remaster")]
        return items

    def artist_albums(
        self, identifier: str, *, include_groups: str, limit: int, offset: int
    ) -> Any:
        """Read original raw-offset release pages.

        Args:
            identifier: Original requested identity.
            include_groups: Original Spotify release-group query.
            limit: Original requested page size.
            offset: Original raw-row release offset.

        Returns:
            Original artist albums result.
        """
        items: list[object] = [raw_album("album"), raw_album("album"), None]
        next_url: str | None = "releases" if offset == 0 else None
        if offset:
            items = [raw_album("second")]
        if self.memory.scenario.profile == "many":
            items = [raw_album(str(index)) for index in range(offset, offset + 23)]
            next_url = "releases" if offset == 0 else None
        if self.memory.scenario.profile in ("empty", "empty-next"):
            items = []
            next_url = (
                "releases" if self.memory.scenario.profile == "empty-next" else None
            )
        page = {"items": items, "next": next_url}
        return self.memory.respond(
            "artist-albums", [identifier, include_groups, limit, offset], page
        )

    def albums(self, identifiers: list[str]) -> Any:
        """Read original ordered album batches and their first track pages.

        Args:
            identifiers: Original ordered identities, retaining duplicate requests.

        Returns:
            Original albums result.
        """
        albums = []
        for identifier in identifiers:
            album = raw_album(identifier)
            album["tracks"] = self.track_page(identifier)
            albums.append(album)
        return self.memory.respond("albums", identifiers, {"albums": albums})

    def track_page(self, identifier: str) -> dict[str, object]:
        """Track page.

        Args:
            identifier: Original requested identity.

        Returns:
            Original track page result.
        """
        page: dict[str, object] = {
            "items": [raw_track("track"), raw_track("track"), None],
            "next": "tracks",
        }
        if self.memory.scenario.profile == "many":
            page["items"] = [raw_track(identifier), raw_track("shared")]
        if self.memory.scenario.profile == "bad-page":
            return {"items": None}
        if self.memory.scenario.profile in ("empty", "empty-next"):
            return {
                "items": [],
                "next": "tracks"
                if self.memory.scenario.profile == "empty-next"
                else None,
            }
        return page

    def album_tracks(self, identifier: str, *, limit: int = 50) -> Any:
        """Read the original first album-track page.

        Args:
            identifier: Original requested identity.
            limit: Original requested page size.

        Returns:
            Original album tracks result.
        """
        return self.memory.respond(
            "album-tracks", [identifier, limit], self.track_page(identifier)
        )

    def next(self, page: object) -> Any:
        """Read the original continuation without inferring offsets.

        Args:
            page: Original raw predecessor page.

        Returns:
            Original next result.
        """
        return self.memory.respond(
            "next", page, {"items": [raw_track("second")], "next": None}
        )

    def current_user_saved_albums_contains(self, identifiers: list[str]) -> Any:
        """Read original saved statuses in ordered batches.

        Args:
            identifiers: Original ordered identities, retaining duplicate requests.

        Returns:
            Original current user saved albums contains result.
        """
        return self.statuses("saved", identifiers)

    def current_user_saved_tracks_contains(self, identifiers: list[str]) -> Any:
        """Read original liked statuses in ordered batches.

        Args:
            identifiers: Original ordered identities, retaining duplicate requests.

        Returns:
            Original current user saved tracks contains result.
        """
        return self.statuses("liked", identifiers)

    def statuses(self, operation: str, identifiers: list[str]) -> Any:
        """Statuses.

        Args:
            operation: Original SDK or membership operation.
            identifiers: Original ordered identities, retaining duplicate requests.

        Returns:
            Original statuses result.
        """
        result: list[object] = [identifier != "second" for identifier in identifiers]
        if self.memory.scenario.profile == "short-status":
            result = []
        if self.memory.scenario.profile == "truthy-status":
            result = ["yes" for _ in identifiers]
        return self.memory.respond(operation, identifiers, result)


def public_lookup(scenario: LookupScenario, catalog: LookupCatalog) -> object:
    """Execute an original public lookup against complete recorded boundaries.

    Args:
        scenario: Original selected workflow.
        catalog: Original SDK boundary fake.

    Returns:
        Original public result.
    """
    spotify = cast(Spotify, catalog)
    workflow = scenario.workflow
    if workflow == "artist-id":
        return library.resolve_live_artist(spotify, artist_id="artist")
    if workflow == "artist-name":
        return library.resolve_live_artist(spotify, name=" Artist ")
    if workflow == "artist-stats":
        return library.get_live_artist_library_stats(spotify, name="Artist")
    if workflow == "album-id":
        return library.resolve_live_album(spotify, album_id="album")
    if workflow == "album-name":
        return library.resolve_live_album(spotify, name=" Album ")
    return other_lookup(scenario, spotify)


def other_lookup(scenario: LookupScenario, spotify: Spotify) -> object:
    """Other lookup.

    Args:
        scenario: Selected original workflow and raw response profile.
        spotify: Caller-owned recorded original SDK boundary.

    Returns:
        Original other lookup result.
    """
    if scenario.workflow == "local-album":
        return library.resolve_album(library.load_your_library_file(), name="Album")
    if scenario.workflow == "local-evaluate":
        return library.evaluate_album(spotify, name="Album")
    if scenario.workflow == "tracklist":
        return library.get_album_tracklist("album", spotify)
    if scenario.workflow == "track-id":
        return scrobbles.resolve_live_track(spotify, track_id="track")
    if scenario.workflow == "track-name":
        return scrobbles.resolve_live_track(spotify, name="Track")
    return scrobbles.get_track_scrobble_status(
        spotify,
        name="Track",
        path=Path("/tmp/history.json"),
        now=datetime(2026, 9, 24, tzinfo=UTC),
    )


def lookup_outcome(
    scenario: LookupScenario,
    catalog: LookupCatalog,
    run: Callable[[LookupScenario, LookupCatalog], object],
) -> object:
    """Lookup outcome.

    Args:
        scenario: Selected original workflow and raw response profile.
        catalog: Recorded original raw Spotify catalog boundary.
        run: Explicit independently supplied workflow runner.

    Returns:
        Original lookup outcome result.
    """
    try:
        return {"result": run(scenario, catalog)}
    except (
        LookupError,
        RuntimeError,
        TypeError,
        ValueError,
        AttributeError,
        SpotifyException,
        blast_from_past.LastFmExportError,
    ) as error:
        return {
            "error": type(error).__name__,
            "message": str(error),
            "candidates": getattr(error, "candidates", None),
            "cause": type(error.__cause__).__name__
            if error.__cause__ is not None
            else None,
        }


def observe_lookup(
    scenario: LookupScenario,
    run: Callable[[LookupScenario, LookupCatalog], object] = public_lookup,
) -> Json:
    """Capture original outcomes, read order and accepted cache state.

    Args:
        scenario: Original raw profile and workflow.

    Returns:
        Immutable original JSON-compatible observation.
    """
    memory = LookupMemory(scenario)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(library, "load_your_library_file", memory.read_library)
        patch.setattr(library, "load_album_tracks_cache", memory.read_cache)
        patch.setattr(library, "save_album_tracks_cache", memory.save_cache)
        patch.setattr(blast_from_past, "load_scrobble_export", memory.history)
        result = lookup_outcome(scenario, LookupCatalog(memory), run)
    return encode_value(
        {
            "outcome": result,
            "events": memory.events,
            "cache": memory.cache,
            "accepted_cache": memory.saved_cache,
        },
        Path("/tmp"),
    )


def ambiguous_item(kind: str) -> list[object]:
    """Ambiguous item.

    Args:
        kind: Original required search resource.

    Returns:
        Original ambiguous item result.
    """
    if kind == "artist":
        return [{"id": "other", "name": "Artist"}]
    if kind == "album":
        return [raw_album("other", artist="Other")]
    return [raw_track("other", artist="Other")]
