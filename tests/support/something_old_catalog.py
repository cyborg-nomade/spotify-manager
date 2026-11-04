"""Native-shaped Spotify and Last.fm observations for Something Old review."""

import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


ARTIST_ID = "a" * 22
OTHER_ARTIST_ID = "b" * 22
PLAYLIST_ID = "p" * 22
RELEASE_ID = "r" * 22
HISTORY_TRACK = "h" * 22
POPULAR_TRACK = "s" * 22


def seed_old_history(path: Path) -> None:
    """Seed one eligible oldest artist without any network history reads.

    Args:
        path: Isolated canonical Last.fm export.
    """
    rows = []
    for index in range(50):
        rows.append(
            {
                "artist": "Old Artist",
                "track": "Old Song",
                "album": "Studio Album",
                "date": 1748779200000 + index * 1000,
            }
        )
    path.write_text(json.dumps({"username": "review", "scrobbles": rows}))


def _artist(identity: str, name: str) -> dict[str, object]:
    return {
        "id": identity,
        "uri": f"spotify:artist:{identity}",
        "name": name,
        "popularity": 40,
        "followers": {"total": 100},
    }


def _release(identity: str, name: str) -> dict[str, object]:
    return {
        "id": RELEASE_ID,
        "uri": f"spotify:album:{RELEASE_ID}",
        "name": "Studio Album",
        "album_type": "album",
        "release_date": "2020-01-01",
        "total_tracks": 2,
        "artists": [_artist(identity, name)],
    }


def _track(identity: str, artist_id: str, artist_name: str) -> dict[str, object]:
    title = "Old Song" if identity == HISTORY_TRACK else "Popular Song"
    return {
        "id": identity,
        "uri": f"spotify:track:{identity}",
        "name": title,
        "album": _release(artist_id, artist_name),
        "artists": [_artist(artist_id, artist_name)],
        "disc_number": 1,
        "track_number": 1 if identity == HISTORY_TRACK else 2,
        "popularity": 50,
    }


@dataclass
class OldChoiceSpotify:
    """Retain actual fake playlist effects and stable artist mappings.

    Args:
        playlist: Current ordered raw track identities.
        writes: Accepted append batches.
        artist_id: Current accepted Spotify identity.
        artist_name: Current Spotify label; identity survives label changes.
        ambiguous: Offer a same-name second artist during resolution.
        fail_after_append: Lose one append response after its effect is accepted.
    """

    playlist: list[str] = field(default_factory=list)
    writes: list[list[str]] = field(default_factory=list)
    artist_id: str = ARTIST_ID
    artist_name: str = "Old Artist"
    ambiguous: bool = False
    fail_after_append: bool = False

    def set_event_callback(self, observer: object) -> None:
        """Accept the native event resource without creating an external client.

        Args:
            observer: Invocation-owned observer.
        """

    async def _get(self, path: str, *, limit: int, offset: int) -> dict[str, object]:
        """Read actual current membership at raw Spotify offsets.

        Args:
            path: Requested playlist endpoint.
            limit: Requested page length.
            offset: Requested raw offset.

        Returns:
            Native-shaped complete playlist page.
        """
        assert path == f"playlists/{PLAYLIST_ID}/items"
        items = self.playlist[offset : offset + limit]
        rows = [
            {"item": _track(identity, self.artist_id, self.artist_name)}
            for identity in items
        ]
        return {
            "items": rows,
            "total": len(self.playlist),
            "next": "more" if offset + len(items) < len(self.playlist) else None,
        }

    async def _post(self, path: str, *, payload: dict[str, object]) -> None:
        """Accept a complete append, optionally losing the response afterward.

        Args:
            path: Playlist append endpoint.
            payload: Original ordered URI batch.

        Raises:
            RuntimeError: One accepted append response is lost.
        """
        assert path == f"playlists/{PLAYLIST_ID}/items"
        uris = payload["uris"]
        assert isinstance(uris, list)
        identities = [str(uri).removeprefix("spotify:track:") for uri in uris]
        self.playlist.extend(identities)
        self.writes.append(identities)
        if self.fail_after_append:
            self.fail_after_append = False
            raise RuntimeError("accepted append response lost")

    async def search(
        self, q: str, *, limit: int, offset: int, **parameters: str
    ) -> dict[str, object]:
        """Return stable exact-name artists or the canonical historical title.

        Args:
            q: Actual source query.
            parameters: Requested Spotify object kind and other SDK keywords.
            limit: Requested result count.
            offset: Requested first result.

        Returns:
            Qualified native-shaped artist or track response.
        """
        if parameters["type"] == "track":
            return {
                "tracks": {
                    "items": [_track(HISTORY_TRACK, self.artist_id, self.artist_name)]
                }
            }
        assert parameters["type"] == "artist"
        artists = [_artist(self.artist_id, self.artist_name)]
        if self.ambiguous:
            artists.append(_artist(OTHER_ARTIST_ID, self.artist_name))
        return {"artists": {"items": artists}}

    async def artist_top_tracks(self, artist_id: str) -> dict[str, object]:
        """Read current popular tracks for the accepted artist.

        Args:
            artist_id: Selected stable Spotify identity.

        Returns:
            Two distinct playable popular tracks.
        """
        return {
            "tracks": [
                _track(POPULAR_TRACK, artist_id, self.artist_name),
                _track(HISTORY_TRACK, artist_id, self.artist_name),
            ]
        }

    async def current_user_saved_tracks_contains(self, tracks: list[str]) -> list[bool]:
        """Return explicit membership for automatic historical matching.

        Args:
            tracks: Candidate track identities.

        Returns:
            Exact positive membership observations.
        """
        return [True] * len(tracks)

    async def artist_albums(
        self, artist_id: str, *, include_groups: str, limit: int, offset: int
    ) -> dict[str, object]:
        """Read one eligible studio album at the actual catalog boundary.

        Args:
            artist_id: Accepted artist.
            include_groups: Existing studio/EP source groups.
            limit: Requested page size.
            offset: Requested raw page offset.

        Returns:
            Complete studio catalog.
        """
        return {"items": [_release(artist_id, self.artist_name)], "next": None}

    async def current_user_saved_albums_contains(self, albums: list[str]) -> list[bool]:
        """Return explicit preferred-edition membership observations.

        Args:
            albums: Candidate release identities.

        Returns:
            No saved preferred editions in this fixture.
        """
        return [False] * len(albums)

    async def album_tracks(
        self, album_id: str, *, limit: int, offset: int
    ) -> dict[str, object]:
        """Read the complete chronological album track list.

        Args:
            album_id: Accepted release identity.
            limit: Requested page length.
            offset: Requested raw offset.

        Returns:
            Two playable album tracks.
        """
        assert album_id == RELEASE_ID
        return {
            "items": [
                _track(HISTORY_TRACK, self.artist_id, self.artist_name),
                _track(POPULAR_TRACK, self.artist_id, self.artist_name),
            ],
            "next": None,
        }
