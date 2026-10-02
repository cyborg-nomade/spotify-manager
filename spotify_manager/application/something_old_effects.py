"""History, interaction, catalog, write and audit boundaries for Something Old."""

from datetime import datetime
from typing import Protocol

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble


class SomethingOldEffects(Protocol):
    """Original caller-owned facts, interaction and accepted-effect seams."""

    def clock(self) -> datetime:
        """Read the original effective UTC timestamp.

        Returns:
            Original supplied or current timestamp.
        """

    def progress(self, message: str) -> None:
        """Present original optional progress text.

        Args:
            message: Original stage text.
        """

    def playlist_length(self, recheck: bool) -> int:
        """Read initial membership or the original pre-write recheck.

        Args:
            recheck: Whether the read is the final empty-playlist guard.

        Returns:
            Original observed destination length.
        """

    def history(self, now: datetime, preview: bool) -> ScrobbleHistorySummary:
        """Refresh original history only after observing an empty destination.

        Args:
            now: Original effective timestamp.
            preview: Original history preview behavior.

        Returns:
            Original complete history refresh summary.
        """

    def ranking(self, history: tuple[Scrobble, ...]) -> tuple[GoldenOldieArtist, ...]:
        """Apply the original configured exact-label Golden Oldies ranking.

        Args:
            history: Original refreshed history facts.

        Returns:
            Original eligible ordered artists.
        """

    def resolve(self, artist: GoldenOldieArtist) -> SpotifyArtistCandidate | None:
        """Interact only when original exact-artist mapping requires a choice.

        Args:
            artist: Original selected Golden Oldies artist.

        Returns:
            Original accepted mapping or artist-choice cancellation.
        """

    def mode(self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate) -> str:
        """Request the original selection mode after accepting an artist.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original requested mode or cancellation.
        """

    def lastfm_tracks(self, artist: GoldenOldieArtist) -> tuple[SelectedTrack, ...]:
        """Resolve original most-scrobbled title markers.

        Args:
            artist: Original selected history artist.

        Returns:
            Original ordered selected markers.
        """

    def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Resolve original popular-track markers.

        Args:
            artist: Original accepted Spotify mapping.

        Returns:
            Original ordered selected markers.
        """

    def album_tracks(
        self,
        artist: GoldenOldieArtist,
        mapped: SpotifyArtistCandidate,
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        """Interact with original studio releases and return complete tracklists.

        Args:
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.

        Returns:
            Original release/markers or album-choice cancellation.
        """

    def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Accept the original complete marker append after the empty recheck.

        Args:
            tracks: Original selected markers in source order.
        """

    def audit(self, summary: SomethingOldSummary) -> None:
        """Accept the original real-run audit after the complete append.

        Args:
            summary: Original complete selected outcome.
        """
