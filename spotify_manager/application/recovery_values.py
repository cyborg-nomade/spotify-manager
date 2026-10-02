"""Typed input, progress, and results for removed-album recovery."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.domain.library import AlbumArtist


def _no_persistence() -> None:
    pass


@dataclass(frozen=True)
class RemovedAlbumRecord:
    """Identity retained in the removal log.

    Args:
        spotify_id: Original album identifier.
        album: Original album label.
        artist: Original primary artist label.
    """

    spotify_id: str
    album: str
    artist: str


@dataclass
class RecoveryState:
    """Mutable completed work with explicit persistence ownership.

    Args:
        processed_album_ids: Completed album identifiers.
        checked_artist_ids: Completed artist-follow checks.
        persist: Existing persistence callback, a no-op for detached state.
    """

    processed_album_ids: set[str]
    checked_artist_ids: set[str]
    persist: Callable[[], None] = field(default=_no_persistence, repr=False)


@dataclass(frozen=True)
class RecoveryAlbum:
    """Parsed album observations; fallback labels remain a use-case decision.

    Args:
        name: Nonempty observed display name, when present.
        uri: Nonempty observed URI, when present.
        artists: Distinct credited artists in their original order.
        release_date: Original date text, including empty and malformed strings.
        precision: Original precision text, including malformed strings.
    """

    name: str | None
    uri: str | None
    artists: tuple[AlbumArtist, ...]
    release_date: str | None
    precision: str | None


@dataclass(frozen=True)
class RecoverySummary:
    """Counts from one invocation, retaining the original result shape.

    Args:
        processed: Completed albums.
        unavailable: Albums unavailable from Spotify.
        multi_artist_albums: Albums with multiple distinct credited artists.
        artists_checked: Artist membership checks completed.
        artists_followed: New follows or intended follows in a dry run.
        future_releases: Albums whose observed release date is in the future.
        albums_restored: Successful restores or intended restores in a dry run.
    """

    processed: int
    unavailable: int
    multi_artist_albums: int
    artists_checked: int
    artists_followed: int
    future_releases: int
    albums_restored: int


@dataclass
class RecoveryCounts:
    """Mutable counts while ordered recovery effects are executing.

    Args:
        processed: Completed albums.
        unavailable: Unavailable albums.
        multiple: Albums with multiple credited artists.
        checked: Completed artist checks.
        followed: Actual or previewed new follows.
        future: Future releases.
        restored: Actual or previewed restores.
    """

    processed: int = 0
    unavailable: int = 0
    multiple: int = 0
    checked: int = 0
    followed: int = 0
    future: int = 0
    restored: int = 0

    def summary(self) -> RecoverySummary:
        """Snapshot completed work into the public result.

        Returns:
            The original immutable result fields.
        """
        return RecoverySummary(
            self.processed,
            self.unavailable,
            self.multiple,
            self.checked,
            self.followed,
            self.future,
            self.restored,
        )
