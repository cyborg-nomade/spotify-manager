"""Artist-follow decisions shared by album review and removed-album recovery."""

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from spotify_manager.domain.library import AlbumArtist
from spotify_manager.models.your_library import YourLibraryAlbum


@dataclass(frozen=True)
class ArtistPersistenceResult:
    """Original result of recording a newly followed artist.

    Args:
        total_artists_updated: Whether the local artist mirror gained the artist.
        stats_history_updated: Whether the statistics period was updated.
    """

    total_artists_updated: bool
    stats_history_updated: bool


@dataclass(frozen=True)
class ArtistFollowOutcome:
    """Completed artist decision for interface presentation.

    Args:
        action: Original follow or no-op outcome.
        artist: Resolved artist, absent only for an unresolved album credit.
        persistence: Local persistence outcome after a new follow.
    """

    action: Literal["unresolved", "checked", "already-followed", "followed"]
    artist: AlbumArtist | None
    persistence: ArtistPersistenceResult | None = None


class AlbumArtistAccess(Protocol):
    """Resolution, fresh membership, follow, and local recording boundaries."""

    def resolve(self, album: YourLibraryAlbum) -> AlbumArtist | None:
        """Resolve the original primary artist from local facts or metadata.

        Args:
            album: Current library item.

        Returns:
            Resolved identity, or None when no usable identifier exists.
        """

    def followed(self, artist: AlbumArtist) -> bool:
        """Read the artist's current membership.

        Args:
            artist: Resolved identity.

        Returns:
            Original truthy first-status interpretation.
        """

    def follow(self, artist: AlbumArtist) -> None:
        """Follow one artist.

        Args:
            artist: Resolved identity.
        """

    def record(self, artist: AlbumArtist) -> ArtistPersistenceResult:
        """Record the follow in the artist mirror and statistics.

        Args:
            artist: Resolved identity.

        Returns:
            Original ordered persistence result.
        """


def follow_album_artist(
    access: AlbumArtistAccess, album: YourLibraryAlbum, checked_ids: set[str]
) -> ArtistFollowOutcome:
    """Resolve and follow an artist once, preserving accepted-write boundaries.

    Args:
        access: Existing observations and ordered effects.
        album: Current review item.
        checked_ids: Mutable identities already checked during this invocation.

    Returns:
        Completed outcome for presentation after marking the identity checked.

    Raises:
        RuntimeError: An integration fails; accepted prior effects remain visible.
    """
    artist = access.resolve(album)
    if artist is None:
        return ArtistFollowOutcome("unresolved", None)
    if artist.spotify_id in checked_ids:
        return ArtistFollowOutcome("checked", artist)
    if access.followed(artist):
        checked_ids.add(artist.spotify_id)
        return ArtistFollowOutcome("already-followed", artist)
    access.follow(artist)
    persistence = access.record(artist)
    checked_ids.add(artist.spotify_id)
    return ArtistFollowOutcome("followed", artist, persistence)
