"""Native-shaped catalogue for complete New Kids plan/transfer integration."""

from spotify_manager.client.lastfm import LastFmRecentTrack
from tests.routines.test_new_kids import FakeSpotify
from tests.routines.test_new_kids import raw_release
from tests.routines.test_new_kids import raw_track


class EmptyPlanHistory:
    """Return no new plays while exercising the actual shared history refresh."""

    async def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Read a synthetic empty history delta.

        Args:
            from_timestamp: Existing inclusive refresh boundary.
            to_timestamp: Existing invocation deadline.
            limit: Existing requested page size.

        Returns:
            No additional plays.
        """
        return ()


class NewKidsPlanSpotify(FakeSpotify):
    """Expose studios, an EP and optional releases with mutable playlist effects."""

    def __init__(self) -> None:
        """Start with one Queue 2 artist and no New Kids markers."""
        super().__init__()
        records = []
        for key, name, kind, count in (
            ("a", "First studio", "album", 2),
            ("b", "Second studio", "album", 2),
            ("c", "Third studio", "album", 2),
            ("d", "Fourth studio", "album", 2),
            ("e", "An EP", "single", 4),
            ("s", "A single", "single", 1),
            ("l", "A live album", "album", 2),
            ("m", "A compilation", "compilation", 2),
            ("q", "Queue album", "album", 2),
        ):
            record = raw_release(key * 22, name, album_type=kind, total_tracks=count)
            records.append(record)
            self.release_tracks[key * 22] = _tracks(key, record, count)
        self.artist_releases["artist"] = records
        self.playlists["queue"] = [self.release_tracks["q" * 22][-1]]


def _tracks(key: str, record: dict[str, object], count: int) -> list[dict[str, object]]:
    values = []
    for index in range(count):
        values.append(
            raw_track(
                key * 20 + f"{index:02d}",
                f"{record['name']} · track {index + 1}",
                record,
                track_number=index + 1,
            )
        )
    return values
