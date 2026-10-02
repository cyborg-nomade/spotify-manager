"""Independent scripted observations for artist completion and discovery review."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease


@dataclass
class Catalog:
    """Script catalog facts while recording every application boundary.

    Args:
        releases: Release tracks supplied on demand.
        albums: Live saved membership observations.
        liked_statuses: Live liked membership observations.
        top: Eligible top-track response.
        popularity: Fallback live popularities.
        events: Ordered requested observations.
    """

    releases: dict[str, tuple[CatalogTrack, ...]] = field(default_factory=dict)
    albums: dict[str, bool] = field(default_factory=dict)
    liked_statuses: dict[str, bool] = field(default_factory=dict)
    top: tuple[CatalogTrack, ...] = ()
    popularity: dict[str, int] = field(default_factory=dict)
    events: list[tuple[str, object]] = field(default_factory=list)

    def saved(self, ids: list[str]) -> dict[str, bool]:
        """Read scripted album memberships.

        Args:
            ids: Requested catalog IDs, retaining duplicates.

        Returns:
            Detached accepted observations.
        """
        self.events.append(("saved", ids))
        return dict(self.albums)

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read tracks for one previously unobserved release.

        Args:
            release: Requested catalog entry.

        Returns:
            Scripted response, including empty releases.
        """
        self.events.append(("tracks", release.spotify_id))
        return self.releases.get(release.spotify_id, ())

    def liked(self, ids: list[str], *, top: bool = False) -> dict[str, bool]:
        """Read scripted likes at the requested context boundary.

        Args:
            ids: Requested unique catalog IDs or ordered top-track IDs.
            top: Whether the request belongs to top-track selection.

        Returns:
            Detached observed memberships.
        """
        self.events.append(("top_likes" if top else "likes", ids))
        return dict(self.liked_statuses)

    def top_tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Observe artist top tracks after catalog assessment.

        Args:
            artist_id: Artist being assessed.

        Returns:
            Original-order scripted response.
        """
        self.events.append(("top", artist_id))
        return self.top

    def popularities(self, ids: list[str]) -> dict[str, int]:
        """Observe fallback popularity only when needed.

        Args:
            ids: Unique liked primary-artist tracks.

        Returns:
            Detached scripted popularities.
        """
        self.events.append(("popularity", ids))
        return dict(self.popularity)
