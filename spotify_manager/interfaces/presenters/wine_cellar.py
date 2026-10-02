"""Original Wine Cellar transfer wording after accepted or previewed effects."""

from collections.abc import Callable

from spotify_manager.domain.catalog import PlaylistTrack


def present_transfer(
    echo: Callable[[str], None], source: PlaylistTrack, duplicate: bool, dry_run: bool
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
    echo(f"{verb} from Wine Cellar: {source.primary_artist_name} - {source.name}")
