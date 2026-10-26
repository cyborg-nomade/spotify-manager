"""Named external catalog and playlist operations for the annual retrospective."""

from typing import Literal
from typing import Protocol

from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack


class AnnualLookup(Protocol):
    """Named original external observations for the corresponding annual stage."""

    def search(self, item: YearEntry) -> tuple[SpotifyTrackMatch, ...]:
        """Search the original artist and title.

        Args:
            item: Ranked display artist and title.

        Returns:
            Qualified matches in encounter order.
        """

    def album(self, artist: str, name: str) -> SpotifyAlbum | None:
        """Search the original release.

        Args:
            artist: Original artist spelling.
            name: Original release title.

        Returns:
            Original accepted release or no match.
        """

    def first(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Read the original first playable marker.

        Args:
            album: Accepted release.

        Returns:
            Original playable first marker.
        """

    def artist(self, name: str) -> SpotifyArtistCandidate | None:
        """Read the exact original artist mapping.

        Args:
            name: Original historical artist label.

        Returns:
            Original mapping or cancellation.
        """

    def primary(self, uri: str) -> object:
        """Read the original first credit.

        Args:
            uri: Prospective playable marker.

        Returns:
            Unchecked original primary credit.
        """


class AnnualPlaylist(Protocol):
    """Named original external observations for the corresponding annual stage."""

    def playlist(self, identity: str) -> tuple[PlaylistTrack, ...]:
        """Read complete current playlist markers.

        Args:
            identity: Source or destination identity.

        Returns:
            Ordered current playable markers.
        """

    def append(self, playlist: str, uris: list[str], top: bool) -> None:
        """Append the original absent markers.

        Args:
            playlist: Original destination identity.
            uris: Complete absent marker batch.
            top: Whether insertion starts at the front.
        """

    def move(self, playlist: str, position: int) -> None:
        """Move one original marker to the front.

        Args:
            playlist: Destination identity.
            position: Observed current marker position.
        """


class AnnualChartCatalog(Protocol):
    """Named original external observations for the corresponding annual stage."""

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Read owned playlists.

        Returns:
            Complete original ownership facts.
        """

    def create(self, name: str, kind: Literal["tracks", "albums"], year: int) -> str:
        """Create the original private annual chart.

        Args:
            name: Original chart name.
            kind: Chart category.
            year: Completed source year.

        Returns:
            Accepted chart identity.
        """

    def playlist(self, identity: str) -> tuple[PlaylistTrack, ...]:
        """Read complete current playlist markers.

        Args:
            identity: Source or destination identity.

        Returns:
            Ordered current playable markers.
        """

    def replace(self, playlist: str, uris: list[str]) -> None:
        """Replace the original chart contents.

        Args:
            playlist: Original chart identity.
            uris: Original rank-ordered marker URIs.
        """


class AnnualCatalog(AnnualLookup, AnnualPlaylist, AnnualChartCatalog, Protocol):
    """Complete invocation-owned annual SDK and playlist boundary."""
