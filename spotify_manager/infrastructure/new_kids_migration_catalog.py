"""Translate only missing current editions into recoverable migration choices."""

from spotipy.exceptions import SpotifyException

from spotify_manager.application.new_kids_migration_selection import (
    MigrationReleaseMissingError,
)
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryCatalog


class NewKidsMigrationCatalog(LegacyDiscoveryCatalog):
    """Keep normal reads/retries while allowing explicit missing-edition resolution.

    Args:
        client: Invocation-owned Spotify client.
        retry: Existing retry and cancellation boundary.
    """

    async def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read an exact edition without substituting a canonical candidate.

        Args:
            release: Current or explicitly chosen edition.

        Returns:
            Existing ordered track observations.

        Raises:
            MigrationReleaseMissingError: Spotify reports this edition missing.
            SpotifyException: Another failure belongs to the existing retry policy.
        """
        try:
            return await super().tracks(release)
        except SpotifyException as exc:
            if exc.http_status not in {404, 410}:
                raise
            raise MigrationReleaseMissingError(
                "The current edition is unavailable; "
                "choose its correct edition explicitly."
            ) from exc
