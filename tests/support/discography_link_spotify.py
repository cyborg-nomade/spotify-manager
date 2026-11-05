"""Native-shaped Discographies catalog with exact externally supplied album reads."""

from spotipy.exceptions import SpotifyException

from tests.routines.test_discography import raw_release
from tests.routines.test_new_wine import FakeSpotify
from tests.routines.test_new_wine import raw_track


FIRST_LINK = "m" * 22
SECOND_LINK = "n" * 22
MISSING_LINK = "x" * 22


def artist_releases(artist: str, count: int) -> list[dict[str, object]]:
    """Build distinct canonical records in stable chronological order.

    Args:
        artist: Primary artist ID.
        count: Number of fetched canonical records.

    Returns:
        Raw native-shaped artist albums.
    """
    records = []
    for index in range(count):
        records.append(
            raw_release(
                f"{artist[0]}{index:021d}",
                f"Record {index + 1}",
                release_date=f"{2000 + index}",
                artist_id=artist,
            )
        )
    return records


def _marker(artist: str, name: str, identity: str) -> dict[str, object]:
    release = raw_release(
        f"{artist}-marker-album", "Marker album", release_date="1999", artist_id=artist
    )
    return raw_track(
        identity, "Queue marker", release, artist_id=artist, artist_name=name
    )


class DiscographyLinkSpotify(FakeSpotify):
    """Simulate real reads and source removals without changing application stages."""

    def __init__(self) -> None:
        """Seed three nonempty queues and two albums absent from the fetched catalog."""
        super().__init__()
        self.playlists = {
            "newfoundland": [_marker("artist", "Artist", "a-marker")],
            "memory": [_marker("beta", "Beta", "b-marker")],
            "requeue": [_marker("cedar", "Cedar", "c-marker")],
            "queue3": [_marker("artist", "Artist", "a-extra")],
        }
        self.artist_releases = {
            "artist": artist_releases("artist", 8),
            "beta": artist_releases("beta", 2),
            "cedar": artist_releases("cedar", 8),
        }
        other = raw_release(
            SECOND_LINK, "Unlisted live record", release_date="2011", artist_id="guest"
        )
        other["artists"] = [
            {"id": "guest", "name": "Guest Artist"},
            {"id": "artist", "name": "Artist"},
        ]
        self.linked_albums: dict[str, object] = {
            FIRST_LINK: raw_release(
                FIRST_LINK,
                "Record 1 (Deluxe Edition)",
                release_date="2010",
                artist_id="artist",
            ),
            SECOND_LINK: other,
        }
        self.album_calls: list[str] = []

    async def artist_albums(
        self, artist_id: str, *, include_groups: str, limit: int, offset: int
    ) -> dict[str, object]:
        """Return complete raw pages for the unchanged catalog reader.

        Args:
            artist_id: Primary artist being discovered.
            include_groups: Existing album/single/compilation fetch categories.
            limit: Existing page size.
            offset: Raw pagination cursor.

        Returns:
            Complete native-shaped page and continuation authority.
        """
        assert include_groups == "album,single,compilation"
        values = self.artist_releases.get(artist_id, [])
        items = values[offset : offset + limit]
        return {
            "items": items,
            "next": "next" if offset + len(items) < len(values) else None,
        }

    async def album(self, identity: str, market: str | None = None) -> object:
        """Return the exact linked edition, including records outside artist discovery.

        Args:
            identity: Requested exact album ID.
            market: Existing optional native market parameter.

        Returns:
            Raw linked album metadata.

        Raises:
            SpotifyException: The synthetic album is unavailable.
        """
        self.album_calls.append(identity)
        if identity not in self.linked_albums:
            raise SpotifyException(404, -1, "Unavailable synthetic album")
        return self.linked_albums[identity]
