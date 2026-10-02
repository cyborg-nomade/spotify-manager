"""Resolve original annual tracks, albums and mapped primary artist markers."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_selection import selected_track
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack


@dataclass(frozen=True)
class AnnualResolution:
    """Bind original caller-owned search and marker facts.

    Args:
        search: Original complete qualified track matches.
        album: Original selected Spotify album or no match.
        first: Original complete first release track.
        artist: Original exact artist mapping or cancellation.
        primary: Original raw first-credit identity of a prospective marker.
    """

    search: Callable[[YearEntry], tuple[SpotifyTrackMatch, ...]]
    album: Callable[[str, str], SpotifyAlbum | None]
    first: Callable[[SpotifyAlbum], SpotifyFirstTrack]
    artist: Callable[[str], SpotifyArtistCandidate | None]
    primary: Callable[[str], object]

    def track(self, item: YearEntry) -> str:
        """Select the original first exact or first qualified track marker.

        Args:
            item: Original ranked display artist/title facts.

        Returns:
            Original selected playable URI.

        Raises:
            NewYearError: The original search has no match.
        """
        candidate = selected_track(self.search(item))
        if candidate is None:
            raise NewYearError(
                f"No Spotify track match: {item['artist']} — {item['name']}"
            )
        return candidate.uri

    def album_marker(self, item: YearEntry) -> str:
        """Resolve the original release before reading its complete first marker.

        Args:
            item: Original ranked artist/release display facts.

        Returns:
            Original selected first marker URI.

        Raises:
            NewYearError: The original album lookup has no match.
        """
        album = self.album(item["artist"], item["name"])
        if album is None:
            raise NewYearError(
                f"No Spotify album match: {item['artist']} — {item['name']}"
            )
        return self.first(album).uri

    def artist_identity(self, item: YearEntry) -> str:
        """Resolve the original exact primary identity without introducing interaction.

        Args:
            item: Original ranked display artist facts.

        Returns:
            Original mapped primary artist identity.

        Raises:
            NewYearError: The original mapping is cancelled or has no match.
        """
        artist = self.artist(item["artist"])
        if artist is None:
            raise NewYearError(f"No Spotify artist match: {item['artist']}")
        return artist.spotify_id
