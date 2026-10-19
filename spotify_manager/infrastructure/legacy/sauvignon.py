"""Bind Sauvignon effects to the existing catalog, history and storage seams."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.sauvignon_values import SauvignonSummary
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_selection import PendingAlbum
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.infrastructure import sauvignon_data
from spotify_manager.infrastructure.recommendation_history import refresh_history
from spotify_manager.routines import sauvignon as legacy


@dataclass
class LegacySauvignon:
    """Keep caller-owned clients and original compatibility helpers at the edge.

    Args:
        spotify: Caller-owned Spotify client.
        lastfm: Caller-owned history source.
        playlist_id: Original destination.
        choice_reader: Original edition interaction.
        retry: Original retry policy.
        export_path: Canonical history location.
        recent_path: Recent history location.
        cache_path: Neighborhood cache location.
        log_path: Original audit destination.
        progress: Original progress callback.
    """

    spotify: Spotify
    lastfm: legacy.LastFmReader
    playlist_id: str
    choice_reader: legacy.AlbumChoiceReader | None
    retry: legacy.RetryCall
    export_path: Path
    recent_path: Path
    cache_path: Path
    log_path: Path
    progress: legacy.ProgressCallback | None

    def refresh(
        self, generated_at: datetime, dry_run: bool
    ) -> tuple[list[Scrobble], int]:
        """Refresh original canonical history.

        Args:
            generated_at: Effective UTC time.
            dry_run: Original preview semantics.

        Returns:
            Ordered plays and live-added count.
        """
        return refresh_history(
            self.lastfm,
            export_path=self.export_path,
            recent_path=self.recent_path,
            dry_run=dry_run,
            now=generated_at,
            progress_callback=self.progress,
        )

    def read(self) -> tuple[PlaylistTrack, ...]:
        """Observe the destination with original error translation.

        Returns:
            Ordered playable markers.

        Raises:
            SauvignonSpotifyError: Original playlist loading fails.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        try:
            return load_playlist_tracks(self.spotify, self.playlist_id, self.retry)
        except legacy.new_wine.NewWineError as exc:
            raise legacy.SauvignonSpotifyError(str(exc)) from exc

    def previous(self) -> set[AlbumKey]:
        """Read original accepted-addition exclusions.

        Returns:
            Original album identities.
        """
        return sauvignon_data.previously_added_album_keys(self.log_path)

    def search(self, candidate: FoundArtCandidate) -> tuple[SpotifyAlbumOption, ...]:
        """Read eligible editions through the original retry boundary.

        Args:
            candidate: Ranked track evidence.

        Returns:
            Original eligible catalog observations.
        """
        from spotify_manager.routines.sauvignon import search_candidate_albums

        return search_candidate_albums(self.spotify, candidate, self.retry)

    def first(self, album: SpotifyAlbumOption) -> FirstTrack:
        """Retain the original first-track observation.

        Args:
            album: Selected edition.

        Returns:
            Original playable marker.
        """
        from spotify_manager.routines.sauvignon import load_first_track

        return load_first_track(self.spotify, album, self.retry)

    def append(self, additions: list[PendingAlbum]) -> None:
        """Accept original ordered additions through the original retry seam.

        Args:
            additions: Freshly filtered proposals.
        """
        from spotify_manager.routines.sauvignon import _append_recommendation_albums

        self.retry(
            partial(
                _append_recommendation_albums,
                self.spotify,
                self.playlist_id,
                additions,
            ),
            f"adding {len(additions)} albums to Sauvignon Terre-Neuve",
        )

    def audit(self, summary: SauvignonSummary) -> None:
        """Append the original outcome to the configured log.

        Args:
            summary: Original completed result.
        """
        sauvignon_data.append_log(summary, self.log_path)
