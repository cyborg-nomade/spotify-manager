"""Model Spotify writes locally for the export job and review browser."""

from dataclasses import replace

from spotify_manager.application.listening_export import PlaylistServiceUnavailableError
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.domain.listening_export import SpotifyDestination


OWNED = "w" * 22
PRIVATE = "v" * 22
OTHER = "u" * 22


class FixturePlaylistGateway:
    """Keep ordered synthetic playlists and optional interrupted writes."""

    def __init__(self) -> None:
        """Start with one public owned destination and one foreign playlist."""
        self.lists = {
            OWNED: SpotifyDestination(
                OWNED, "Existing mix", "owner", True, "original", 1
            ),
            OTHER: SpotifyDestination(
                OTHER, "Followed mix", "other", False, "foreign", 0
            ),
        }
        self.tracks: dict[str, list[str]] = {
            OWNED: ["spotify:track:" + "z" * 22],
            OTHER: [],
        }
        self.creates = 0
        self.writes: list[tuple[str, ...]] = []
        self.reject_at = -1
        self.split: int | None = None
        self.ambiguous = False
        self.hide_creation = False
        self.markers: dict[str, str] = {}

    async def account(self) -> str:
        """Return the synthetic account."""
        return "owner"

    async def destinations(self, account: str) -> tuple[SpotifyDestination, ...]:
        """Return only the synthetic account's own playlists."""
        return tuple(row for row in self.lists.values() if row.owner == account)

    async def destination(self, identity: str) -> SpotifyDestination:
        """Return the playlist and its most recent synthetic snapshot."""
        return self.lists[identity]

    async def create(
        self, target: ExportTarget, marker: str
    ) -> SpotifyDestination | None:
        """Create a private destination, optionally hiding the acknowledgment."""
        self.creates += 1
        self.markers[marker] = PRIVATE
        record = SpotifyDestination(
            PRIVATE, target.name, target.account, False, "empty", 0
        )
        self.lists[PRIVATE] = record
        self.tracks[PRIVATE] = []
        return None if self.hide_creation else record

    async def locate_created(
        self, account: str, marker: str
    ) -> SpotifyDestination | None:
        """Find a previously requested creation when it becomes visible."""
        if self.hide_creation or marker not in self.markers:
            return None
        return self.lists[self.markers[marker]]

    async def append(self, playlist: str, uris: tuple[str, ...]) -> str | None:
        """Append the exact batch or simulate a provider interruption."""
        self.writes.append(uris)
        if len(self.writes) == self.reject_at:
            raise PlaylistServiceUnavailableError("Wait and retry.")
        applied = uris if self.split is None else uris[: self.split]
        self.split = None
        self.commit_items(playlist, applied)
        return None if self.ambiguous else self.lists[playlist].snapshot

    async def items(
        self, destination: SpotifyDestination, offset: int, count: int
    ) -> tuple[str | None, ...]:
        """Observe only the requested absolute positions."""
        return tuple(self.tracks[destination.identity][offset : offset + count])

    def commit_items(self, identity: str, addition: tuple[str, ...]) -> None:
        """Simulate a freshly visible change at the provider."""
        tracks = self.tracks[identity]
        tracks.extend(addition)
        self.lists[identity] = replace(
            self.lists[identity], count=len(tracks), snapshot=f"snapshot-{len(tracks)}"
        )


class ImmediateStop:
    """Skip observation delays for local tests."""

    def is_set(self) -> bool:
        """Keep allowing the worker to proceed."""
        return False

    async def wait(self, timeout: float | None = None) -> bool:
        """Allow another immediate observation."""
        return False
