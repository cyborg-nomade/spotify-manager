"""Acquire discography facts through the existing catalog and history stages."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotipy import Spotify

from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_execution import DiscographyStateAccess
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.core.state import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.infrastructure.discography_records import catalog_page
from spotify_manager.infrastructure.discography_records import saved_statuses
from spotify_manager.routines import new_wine


if TYPE_CHECKING:
    from spotify_manager.routines import discography as legacy


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _playlist(
    spotify: Spotify, retry: legacy.RetryCall, playlist: str
) -> tuple[PlaylistTrack, ...]:
    from spotify_manager.routines.new_wine import load_playlist_tracks

    try:
        return load_playlist_tracks(spotify, playlist, retry)
    except new_wine.NewWineError as exc:
        raise DiscographyError(str(exc)) from exc


def _page(
    spotify: Spotify, artist: str, retry: legacy.RetryCall, offset: int
) -> DiscographyPage:
    from spotify_manager.routines.discography import _release_page

    return catalog_page(_release_page(spotify, artist, offset, retry), artist)


def _saved(
    spotify: Spotify, retry: legacy.RetryCall, identities: list[str]
) -> list[bool]:
    from spotify_manager.routines.discography import _saved_batch

    raw = _saved_batch(spotify, identities, retry)
    return saved_statuses(raw, len(identities))


@dataclass(frozen=True)
class DiscographySpotify:
    """Own the original catalog and playlist observation boundary.

    Args:
        spotify: Caller-owned SDK client.
        retry: Original read retry policy.
    """

    spotify: Spotify
    retry: legacy.RetryCall

    def read(self, playlist: str) -> tuple[PlaylistTrack, ...]:
        """Read the original playable playlist markers.

        Args:
            playlist: Original source identity.

        Returns:
            Complete checked observations in original order.
        """
        return _playlist(self.spotify, self.retry, playlist)

    def page(self, artist: str, offset: int) -> DiscographyPage:
        """Read an original raw-row catalog page.

        Args:
            artist: Original primary identity.
            offset: Original raw-row cursor.

        Returns:
            Parsed releases and raw continuation authority.
        """
        return _page(self.spotify, artist, self.retry, offset)

    def saved(self, identities: list[str]) -> list[bool]:
        """Read the original checked saved-release statuses.

        Args:
            identities: Original ordered release identities.

        Returns:
            Corresponding validated memberships.
        """
        return _saved(self.spotify, self.retry, identities)


@dataclass(frozen=True)
class DiscographyPriority:
    """Resolve priority authority only when planning reaches its preflight read.

    Args:
        path: Original priority location.
        service: Optional caller-owned shared authority.
    """

    path: Path
    service: StateService | None

    def load(self) -> dict[str, object]:
        """Read the original priority namespace before queue observations.

        Returns:
            Original complete priority namespace retaining unknown fields.
        """
        from spotify_manager.routines.discography import _state_access

        return _state_access(self.path, self.service).load()


@dataclass(frozen=True)
class DiscographyArtistCatalog:
    """Own the original exact-artist SDK leaf and ambiguity interaction.

    Args:
        spotify: Caller-owned SDK client.
        choice: Original optional artist interaction.
        retry: Original read retry policy.
    """

    spotify: Spotify
    choice: legacy.HistoricalArtistChoiceReader | None
    retry: legacy.RetryCall

    def resolve(self, name: str) -> SpotifyArtistCandidate | None:
        """Observe the original exact artist mapping.

        Args:
            name: Historical artist display name.

        Returns:
            Accepted mapping or original cancellation.
        """
        from spotify_manager.routines.something_old import resolve_spotify_artist

        return resolve_spotify_artist(self.spotify, name, self.choice, self.retry)


@dataclass(frozen=True)
class DiscographyWrites:
    """Own confirmed removals, their audit and the final priority store.

    Args:
        spotify: Caller-owned SDK client.
        retry: Original mutation retry policy.
        state_path: Original priority namespace location.
        service: Optional caller-owned shared authority.
        audit_path: Original successful-removal audit location.
        callback: Optional progress notification.
    """

    spotify: Spotify
    retry: legacy.RetryCall
    state_path: Path
    service: StateService | None
    audit_path: Path
    callback: legacy.ProgressCallback | None

    def remove(
        self, selection: ArtistSelection, group: ArtistMarkers, batch: list[str]
    ) -> None:
        """Accept the original retried SDK removal batch.

        Args:
            selection: Original confirmed artist.
            group: Original source marker group.
            batch: Ordered unique removal URIs.
        """
        from spotify_manager.routines.discography import _remove_batch

        _remove_batch(self.spotify, self.retry, selection, group, batch)

    def audit(self, selection: ArtistSelection, next_queue: QueueName) -> None:
        """Append the original successful-removal record.

        Args:
            selection: Original confirmed artist and exact releases.
            next_queue: Original next-run priority.
        """
        from spotify_manager.routines.discography import _append_log

        _append_log(selection, next_queue, self.audit_path)

    def state(self) -> DiscographyStateAccess:
        """Resolve the original priority authority after all accepted removals.

        Returns:
            Original priority namespace access at the accepted effect boundary.
        """
        from spotify_manager.routines.discography import _state_access

        return _state_access(self.state_path, self.service)

    def progress(self, message: str) -> None:
        """Deliver the original optional progress notification.

        Args:
            message: Original per-artist stage text.
        """
        if self.callback is not None:
            self.callback(message)
