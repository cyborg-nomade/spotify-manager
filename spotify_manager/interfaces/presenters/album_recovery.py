"""Original removed-album recovery messages for CLI and HTTP callers."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.recovery_values import RecoveryAlbum
from spotify_manager.application.recovery_values import RecoverySummary
from spotify_manager.application.recovery_values import RemovedAlbumRecord
from spotify_manager.domain.library import AlbumArtist


def announce_artist(
    echo: Callable[[str], None], artist: AlbumArtist, dry_run: bool
) -> None:
    """Present an accepted or previewed credited-artist follow.

    Args:
        echo: Original output callback.
        artist: Resolved identity.
        dry_run: Whether the invocation previews the follow.
    """
    prefix = "Would follow" if dry_run else "Followed"
    echo(f"{prefix} credited artist: {artist.name}")


@dataclass(frozen=True)
class RecoveryPresenter:
    """Deliver recovery output through the invoking interface's sink.

    Args:
        echo: Original message callback.
    """

    echo: Callable[[str], None]

    def unavailable(self, record: RemovedAlbumRecord) -> None:
        """Show an unavailable album.

        Args:
            record: Original identity and labels.
        """
        self.echo(f"Album unavailable from Spotify: {record.album} - {record.artist}")

    def credits(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> None:
        """Show all distinct credited artists in observed order.

        Args:
            album: Parsed album observations.
            record: Original fallback labels.
        """
        names = ", ".join(artist.name for artist in album.artists)
        self.echo(
            f"Multiple credited artists ({len(album.artists)}): "
            f"{album.name or record.album} - {names}"
        )

    def future(
        self, record: RemovedAlbumRecord, release_date: str | None, status: str
    ) -> None:
        """Show the original future-release outcome.

        Args:
            record: Original removal-log labels.
            release_date: Observed date text.
            status: Existing outcome prefix.
        """
        self.echo(f"{status} ({release_date}): {record.album} - {record.artist}")

    def finish(self, summary: RecoverySummary, dry_run: bool) -> None:
        """Present the original final counts.

        Args:
            summary: Completed outcomes.
            dry_run: Whether this invocation previewed writes.
        """
        mode = "Dry run complete" if dry_run else "Recovery complete"
        self.echo(
            f"{mode}. Processed: {summary.processed}. "
            f"Unavailable: {summary.unavailable}. "
            f"Multi-artist albums: {summary.multi_artist_albums}. "
            f"Artists checked: {summary.artists_checked}. "
            f"Artists followed: {summary.artists_followed}. "
            f"Future releases: {summary.future_releases}. "
            f"Restored: {summary.albums_restored}."
        )
