"""Shared studio catalog observations behind the original synchronous SDK helpers."""

from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.catalog import release_candidate
from spotify_manager.domain.discography import select_editions
from spotify_manager.routines import new_wine


@dataclass(frozen=True)
class StudioCatalogAccess:
    """Gather original studio observations and apply shared pure edition selection.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Original request retry and cancellation boundary.
    """

    client: Spotify
    retry: RetryCall

    async def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Observe candidates then saved membership before selecting studio editions.

        Args:
            artist_id: Original primary artist identifier.

        Returns:
            Domain-selected canonical releases in original chronological order.

        Raises:
            SlowListeningError: Original catalog or saved-membership parsing fails.
        """
        from spotify_manager.routines.slow_listening import _load_candidates
        from spotify_manager.routines.slow_listening import _load_saved_statuses

        releases = await _load_candidates(self.client, artist_id, self.retry)
        saved = await _load_saved_statuses(self.client, releases, self.retry)
        observed = []
        for release in releases:
            observed.append(
                replace(release, saved=saved.get(release.spotify_id, False))
            )
        return select_editions(observed)

    async def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read ordered tracks with the original shared release-error translation.

        Args:
            release: Selected canonical studio edition.

        Returns:
            Playable tracks in original disc/track order.

        Raises:
            SlowListeningError: The original release-track reader fails.
        """
        from spotify_manager.routines.new_wine import (
            async_load_release_tracks as load_release_tracks,
        )

        try:
            return await load_release_tracks(
                self.client, release_candidate(release), self.retry
            )
        except new_wine.NewWineError as exc:
            raise SlowListeningError(str(exc)) from exc
