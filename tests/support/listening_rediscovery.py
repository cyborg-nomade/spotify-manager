"""Supply paged Spotify album fixtures without using an external service."""

from spotify_manager.infrastructure.listening.album_tracklists import (
    SpotifyAlbumTracklists,
)


class FixtureAlbumPages:
    """Return small album pages with the positions deliberately out of order."""

    async def client(self) -> FixtureAlbumPages:
        """Return the same named synthetic owner as the API resource."""
        return self

    async def album_tracks(
        self, album_id: str, *, limit: int, offset: int
    ) -> dict[str, object]:
        """Return two pages for a synthetic, two-disc release."""
        if album_id.startswith("x"):
            return {"items": [], "offset": offset, "total": 3, "next": "incomplete"}
        return _fixture_page(album_id, offset)


def _fixture_page(album_id: str, offset: int) -> dict[str, object]:
    first = (
        _fixture_track(album_id[0], "=Album opener", 1, 1),
        _fixture_track("7", "Second song", 1, 2),
    )
    last = _fixture_track("8", "Disc two", 2, 1)
    return {
        "items": list(first) if offset else [last],
        "offset": offset,
        "total": 3,
        "next": None if offset else "following page",
    }


def _fixture_track(
    identity: str, name: str, disc: int, track: int
) -> dict[str, object]:
    return {
        "uri": "spotify:track:" + identity * 22,
        "name": name,
        "disc_number": disc,
        "track_number": track,
    }


def fixture_tracklists() -> SpotifyAlbumTracklists:
    """Run the actual Spotify adapter over deterministic local pages."""
    return SpotifyAlbumTracklists(FixtureAlbumPages())
