"""Original Wine Cellar transfer wording after accepted or previewed effects."""

from dataclasses import dataclass

from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.catalog import PlaylistTrack


def present_transfer(
    echo: Messages, source: PlaylistTrack, duplicate: bool, dry_run: bool
) -> None:
    """Render one transfer at its original boundary before checkpoint and audit.

    Args:
        echo: Caller-owned message sink.
        source: Original cellar marker.
        duplicate: Whether its destination marker was already present.
        dry_run: Whether to use preview wording.
    """
    verb = "Would move" if dry_run else "Moved"
    if duplicate:
        verb = "Would remove duplicate" if dry_run else "Removed duplicate"
    echo.echo(f"{verb} from Wine Cellar: {source.primary_artist_name} - {source.name}")


@dataclass(frozen=True)
class CellarPresenter:
    """Present Wine Cellar outcomes through the invoking interface.

    Args:
        output: Original message owner.
    """

    output: Messages

    def moved(self, source: PlaylistTrack, duplicate: bool, dry_run: bool) -> None:
        """Present an accepted or previewed transfer.

        Args:
            source: Original cellar marker.
            duplicate: Whether the destination already had this marker.
            dry_run: Whether the transfer was previewed.
        """
        present_transfer(self.output, source, duplicate, dry_run)
