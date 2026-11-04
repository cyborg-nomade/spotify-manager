"""Small external-service simulation for the actual interactive annual workflow."""

import json
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from typing import cast

from spotify_manager.client.lastfm import LastFmRecentTrack


BLAST = "b" * 22
PALACE = "p" * 22
MEMORY = "m" * 22
QUEUE = "q" * 22


class CapturedSearch(TypedDict):
    """Describe a public catalog query and its opaque Spotify response.

    Args:
        query: Recorded Spotify query text.
        response: Parser-relevant raw response metadata.
    """

    query: str
    response: dict[str, object]


def observed_searches() -> list[CapturedSearch]:
    """Read the public Spotify observations preserved for the reported title.

    Returns:
        Captured public search metadata without credentials or user data.
    """
    path = Path(__file__).parents[1] / "fixtures/catalog_matching/chevelle.json"
    return cast(list[CapturedSearch], json.loads(path.read_text())["searches"])


def _observed_tracks(index: int) -> list[dict[str, object]]:
    page = cast(dict[str, object], observed_searches()[index]["response"]["tracks"])
    return cast(list[dict[str, object]], page["items"])


@dataclass
class AnnualMatchingSpotify:
    """Simulate catalog reads and record accepted writes for annual HTTP/CLI tests.

    Args:
        searches: Recorded search arguments.
        writes: Accepted fake playlist writes.
        playlists: Current fake playlist contents.
        chart_names: Names of newly accepted fake chart identities.
    """

    searches: list[tuple[str, str]] = field(default_factory=list)
    writes: list[tuple[str, object]] = field(default_factory=list)
    playlists: dict[str, list[str]] = field(default_factory=dict)
    chart_names: dict[str, str] = field(default_factory=dict)

    async def search(
        self, q: str, limit: int, offset: int, **parameters: str
    ) -> object:
        """Return observed title results and deliberately unresolved release searches.

        Args:
            q: Original Spotify query.
            limit: Requested page size.
            offset: Requested first-page offset.
            **parameters: Spotify search type.

        Returns:
            A Spotify-shaped catalog page.
        """
        kind = parameters["type"]
        self.searches.append((q, kind))
        captures = observed_searches()
        if kind == "artist":
            track = _observed_tracks(0)[0]
            return {"artists": {"items": track["artists"]}}
        if kind == "album":
            albums = [] if q.startswith("album:") else self._albums()
            return {"albums": {"items": albums}}
        return captures[0 if q.startswith("track:") else 1]["response"]

    def _albums(self) -> list[dict[str, object]]:
        return [
            cast(dict[str, object], track["album"]) for track in _observed_tracks(0)
        ]

    async def current_user_playlists(self, limit: int, offset: int) -> object:
        """Expose the owned source playlists and Queue 3 ownership anchor.

        Args:
            limit: Requested page size.
            offset: Original first page.

        Returns:
            Complete owned playlist metadata.
        """
        items = []
        for identity, name in (
            (QUEUE, "Queue 3"),
            ("o" * 22, "Obsessions 2025"),
            ("d" * 22, "Great Discoveries 2025"),
        ):
            items.append(
                {
                    "id": identity,
                    "name": name,
                    "owner": {"id": "owner"},
                    "tracks": {"total": 0},
                }
            )
        for identity, name in self.chart_names.items():
            items.append(
                {
                    "id": identity,
                    "name": name,
                    "owner": {"id": "owner"},
                    "tracks": {"total": len(self.playlists.get(identity, []))},
                }
            )
        return {"items": items, "total": len(items), "next": None}

    async def _get(self, path: str, limit: int, offset: int) -> object:
        """Return empty source/destination playlists without external reads.

        Args:
            path: Requested playlist-items path.
            limit: Requested page size.
            offset: Requested item offset.

        Returns:
            An empty complete Spotify playlist page.
        """
        assert path.startswith("playlists/")
        uris = self.playlists.get(path.split("/")[1], [])
        items = []
        for uri in uris[offset : offset + limit]:
            raw = dict(_observed_tracks(0)[0])
            raw.update(id=uri.rsplit(":", 1)[-1], uri=uri)
            items.append({"item": raw})
        return {"items": items, "total": len(uris), "next": None}

    async def current_user_saved_albums_contains(self, ids: list[str]) -> list[bool]:
        """Return unsaved status for the simulated catalog releases.

        Args:
            ids: Requested release identities.

        Returns:
            Parallel unsaved statuses.
        """
        return [False] * len(ids)

    async def album_tracks(self, album_id: str, limit: int, offset: int) -> object:
        """Provide one complete playable first marker for the selected release.

        Args:
            album_id: Selected release identity.
            limit: Requested catalog page size.
            offset: Requested track offset.

        Returns:
            Complete playable marker metadata.
        """
        return {
            "items": [
                {
                    "id": "first",
                    "uri": "spotify:track:first",
                    "name": "Opening",
                    "disc_number": 1,
                    "track_number": 1,
                }
            ],
            "next": None,
        }

    async def track(self, track_id: str) -> object:
        """Return the recorded Chevelle credit for primary-artist marker checks.

        Args:
            track_id: Accepted marker identity.

        Returns:
            Complete recorded artist credits.
        """
        return {"artists": self._albums()[0]["artists"]}

    async def current_user(self) -> dict[str, str]:
        """Return the synthetic account owning newly created charts.

        Returns:
            Synthetic owner identity.
        """
        return {"id": "owner"}

    async def user_playlist_create(
        self, user: str, name: str, public: bool, description: str
    ) -> object:
        """Record chart creation without contacting Spotify.

        Args:
            user: Synthetic owner identity.
            name: Planned chart name.
            public: Original private-chart flag.
            description: Original chart description.

        Returns:
            Synthetic accepted chart identity.
        """
        self.writes.append(("create", name))
        identity = "created" + str(len(self.writes))
        self.chart_names[identity] = name
        return {"id": identity}

    async def _put(self, path: str, payload: object) -> None:
        """Record a chart synchronization.

        Args:
            path: Requested Spotify playlist path.
            payload: Complete accepted chart body.
        """
        self.writes.append((path, payload))
        body = cast(dict[str, object], payload)
        identity = path.split("/")[1]
        if "uris" in body:
            self.playlists[identity] = list(cast(list[str], body["uris"]))
            return
        tracks = self.playlists[identity]
        track = tracks.pop(cast(int, body["range_start"]))
        tracks.insert(cast(int, body["insert_before"]), track)

    async def _post(self, path: str, payload: object) -> None:
        """Record an accepted destination append.

        Args:
            path: Requested Spotify playlist path.
            payload: Complete accepted append body.
        """
        self.writes.append((path, payload))
        body = cast(dict[str, object], payload)
        tracks = self.playlists.setdefault(path.split("/")[1], [])
        position = cast(int, body.get("position", len(tracks)))
        tracks[position:position] = cast(list[str], body["uris"])


class AnnualMatchingHistory:
    """Return one historical play from the reported artist/title combination."""

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Supply a completed-year scrobble through the original history-read port.

        Args:
            from_timestamp: Inclusive requested range start.
            to_timestamp: Requested range end.
            limit: Original Last.fm page size.

        Returns:
            One historical play carrying the omitted article.
        """
        stamp = int(datetime(2025, 6, 1, tzinfo=UTC).timestamp())
        return (LastFmRecentTrack("Chevelle", "In Debt to Earth", "Vena Sera", stamp),)
