"""Bind Sauvignon effects to the existing catalog, history and storage seams."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Literal

from spotipy import Spotify

from spotify_manager.application.sauvignon_values import SauvignonSummary
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_selection import PendingAlbum
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed
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
    history: tuple[TrackHistory, ...] = ()

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
        return legacy.found_art.refresh_scrobble_history(
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
        try:
            return legacy.new_wine.load_playlist_tracks(
                self.spotify, self.playlist_id, self.retry
            )
        except legacy.new_wine.NewWineError as exc:
            raise legacy.SauvignonSpotifyError(str(exc)) from exc

    def seeds(
        self, history: list[Scrobble], count: int, week: date
    ) -> tuple[FoundArtSeed, ...]:
        """Aggregate once and select the original weighted seeds.

        Args:
            history: Ordered canonical plays.
            count: Requested seed count.
            week: Effective listening week.

        Returns:
            Original ordered seeds.
        """
        self.history = legacy.found_art.aggregate_track_history(history)
        return legacy.found_art.select_seed_tracks(
            self.history, seed_count=count, week_start=week
        )

    def tracks(
        self,
        seeds: tuple[FoundArtSeed, ...],
        history: list[Scrobble],
        week: date,
        pool: int,
        generated_at: datetime,
    ) -> tuple[FoundArtCandidate, ...]:
        """Gather neighborhoods with the original heard-track exclusions.

        Args:
            seeds: Selected seeds.
            history: Canonical history, already aggregated during seed selection.
            week: Effective listening week.
            pool: Original candidate bound.
            generated_at: Effective UTC time.

        Returns:
            Original ranked track candidates.
        """
        return legacy.found_art.gather_candidates(
            self.lastfm,
            seeds,
            {track.key for track in self.history},
            cache_path=self.cache_path,
            log_path=None,
            week_start=week,
            candidate_pool_size=pool,
            now=generated_at,
            progress_callback=self.progress,
        )

    def previous(self) -> set[AlbumKey]:
        """Read original accepted-addition exclusions.

        Returns:
            Original album identities.
        """
        return legacy.previously_added_album_keys(self.log_path)

    def albums(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        excluded: set[AlbumKey],
        existing: set[str],
        maximum: int,
        week: date,
    ) -> tuple[AlbumRecommendation, ...]:
        """Observe original ranked catalog evidence.

        Args:
            candidates: Original track candidates.
            excluded: Original album exclusions.
            existing: Represented album identities.
            maximum: Original search bound.
            week: Effective listening week.

        Returns:
            Ordered album recommendations.
        """
        return legacy.gather_album_recommendations(
            self.spotify,
            candidates,
            excluded,
            existing,
            maximum_candidates=maximum,
            week_start=week,
            retry_call=self.retry,
            progress_callback=self.progress,
        )

    def choose(
        self, item: AlbumRecommendation
    ) -> SpotifyAlbumOption | Literal["skip", "quit"]:
        """Retain the original edition choice seam.

        Args:
            item: Ranked evidence.

        Returns:
            Selected edition or control response.
        """
        return legacy.choose_album_option(item, self.choice_reader)

    def first(self, album: SpotifyAlbumOption) -> FirstTrack:
        """Retain the original first-track observation.

        Args:
            album: Selected edition.

        Returns:
            Original playable marker.
        """
        return legacy.load_first_track(self.spotify, album, self.retry)

    def append(self, additions: list[PendingAlbum]) -> None:
        """Accept original ordered additions through the original retry seam.

        Args:
            additions: Freshly filtered proposals.
        """
        self.retry(
            partial(
                legacy._append_recommendation_albums,
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
        legacy.append_log(summary, self.log_path)
