"""Bind dormant observations to original synchronous catalog and playlist helpers."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from spotipy import Spotify

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import DormantArtist
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.routines import blast_from_past_artists as legacy


def _match(track: CatalogTrack) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        track.spotify_id,
        track.uri,
        track.name,
        (track.primary_artist_name,),
        "",
        1,
        1.0,
        None,
        track.popularity,
        True,
    )


@dataclass(frozen=True)
class LegacyDormantRecovery:
    """Keep original clients and compatibility seams at the outer edge.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Original destination.
        path: Original canonical history location.
        retry: Original retry policy.
        cancel: Original cancellation callback.
    """

    spotify: Spotify
    playlist_id: str
    path: Path
    retry: legacy.RetryCall
    cancel: legacy.CancelCheck | None

    def candidates(self, today: date) -> tuple[DormantArtist, ...]:
        """Observe original history eligibility.

        Args:
            today: Effective local date.

        Returns:
            Alphabetical candidates.
        """
        from spotify_manager.routines.blast_from_past_artists import dormant_artists

        return dormant_artists(self.path, today=today)

    def read(self) -> PlaylistState:
        """Observe original destination membership.

        Returns:
            Ordered original membership facts.
        """
        from spotify_manager.routines.blast_from_past import load_playlist_state

        return load_playlist_state(
            self.spotify, self.playlist_id, self.retry, self.cancel
        )

    def mapping(
        self, artist: DormantArtist, rank: int
    ) -> SpotifyArtistCandidate | None:
        """Retain the original unique-exact mapping boundary.

        Args:
            artist: Original history candidate.
            rank: Full original candidate position.

        Returns:
            Unique mapping or no match.
        """
        from spotify_manager.routines.blast_from_past_artists import _spotify_artist

        return _spotify_artist(self.spotify, artist, rank, self.retry)

    def track(self, artist_id: str) -> CatalogTrack | None:
        """Observe the original preferred live-liked marker.

        Args:
            artist_id: Original mapped identity.

        Returns:
            Original preferred marker or no liked track.
        """
        from spotify_manager.bootstrap.dormant_artists import dormant_tracks

        return dormant_tracks(self.spotify, artist_id, self.retry).run()

    def append(self, tracks: list[CatalogTrack]) -> None:
        """Convert original markers and accept the existing ordered batch append.

        Args:
            tracks: Original pending markers.
        """
        from spotify_manager.routines.blast_from_past import add_spotify_matches

        matches = [_match(track) for track in tracks]
        add_spotify_matches(
            self.spotify, self.playlist_id, matches, self.retry, self.cancel
        )
