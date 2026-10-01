"""Bind Queue fill stages to the original synchronous SDK and persistence seams."""

from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.queue_fill_effects import QueueFillState
from spotify_manager.application.queue_fill_values import FillResult
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.queue_values import ArtistHistory
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.routines import the_queue as legacy


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


@dataclass
class LegacyQueueFill:
    """Retain caller-owned client, files, retry and presenter behavior.

    Args:
        spotify: Original caller-owned Spotify client.
        lastfm: Original caller-owned Last.fm reader.
        playlists: Original parsed destination identities.
        choice: Original optional artist interaction reader.
        echo: Original text presenter.
        callback: Original optional progress presenter.
        configured_retry: Original optional retry boundary.
        export_path: Original history export location.
        recent_path: Original recent-history location.
        state_path: Original state location.
        state_service: Original optional shared state authority.
        cache_path: Original neighborhood cache location.
        log_path: Original audit location.
        now: Original optional timestamp.
        retry: Effective retry resolved only after request validation.
    """

    spotify: Spotify
    lastfm: legacy.LastFmReader
    playlists: legacy.QueuePlaylists
    choice: legacy.ArtistChoiceReader | None
    echo: legacy.Echo
    callback: legacy.ProgressCallback | None
    configured_retry: legacy.RetryCall | None
    export_path: Path
    recent_path: Path
    state_path: Path
    state_service: StateService | None
    cache_path: Path
    log_path: Path
    now: datetime | None
    retry: legacy.RetryCall = _immediate

    def configure(self) -> None:
        """Resolve original falsey retry behavior after request validation."""
        self.retry = self.configured_retry or _immediate

    def clock(self) -> datetime:
        """Resolve the original effective timestamp.

        Returns:
            Original supplied or current time converted to UTC.
        """
        return (self.now or legacy.datetime.now(UTC)).astimezone(UTC)

    def week(self, now: datetime) -> date:
        """Resolve the original local listening calendar.

        Args:
            now: Original effective timestamp.

        Returns:
            Original effective listening week.
        """
        return legacy.found_art.listening_week_start(now)

    def history(self, preview: bool, now: datetime) -> tuple[Sequence[Scrobble], int]:
        """Preserve original refresh parameters and narrowed error translation.

        Args:
            preview: Original history preview mode.
            now: Original effective timestamp.

        Returns:
            Original refreshed plays and live additions.

        Raises:
            QueueStateError: Original history refresh failed.
        """
        progress = self._history_progress if self.callback is not None else None
        try:
            return legacy.found_art.refresh_scrobble_history(
                self.lastfm,
                export_path=self.export_path,
                recent_path=self.recent_path,
                dry_run=preview,
                now=now,
                progress_callback=progress,
            )
        except legacy.found_art.FoundArtError as exc:
            raise QueueStateError(str(exc)) from exc

    def _history_progress(self, message: str) -> None:
        self.progress(0, 0, message)

    def queue_length(self) -> int:
        """Observe original Queue membership after history refresh.

        Returns:
            Original observed Queue length.
        """
        return len(
            legacy.new_wine.load_playlist_tracks(
                self.spotify, self.playlists.queue, self.retry
            )
        )

    def seeds(
        self,
        history: tuple[ArtistHistory, ...],
        count: int,
        week: date,
    ) -> tuple[ArtistSeed, ...]:
        """Retain the original seed selection seam.

        Args:
            history: Original aggregated history facts.
            count: Original requested seed count.
            week: Original effective listening week.

        Returns:
            Original ordered weighted seeds.
        """
        return legacy.select_seed_artists(history, seed_count=count, week_start=week)

    def candidates(
        self,
        seeds: tuple[ArtistSeed, ...],
        heard: set[str],
        week: date,
        limit: int,
        now: datetime,
    ) -> tuple[ArtistRecommendation, ...]:
        """Retain the original recommendation gathering seam and parameters.

        Args:
            seeds: Original ordered weighted seeds.
            heard: Original heard identities.
            week: Original effective listening week.
            limit: Original candidate pool size.
            now: Original effective timestamp.

        Returns:
            Original ordered weekly recommendations.
        """
        return legacy.gather_artist_recommendations(
            self.lastfm,
            seeds,
            heard,
            cache_path=self.cache_path,
            log_path=self.log_path,
            week_start=week,
            candidate_pool_size=limit,
            now=now,
            progress_callback=self.callback,
        )

    def represented(self) -> set[str]:
        """Retain original destination read order before state loading.

        Returns:
            Original represented Spotify artist identities.
        """
        return legacy._playlist_artist_ids(
            self.spotify,
            (
                self.playlists.queue,
                self.playlists.queue_2,
                self.playlists.new_kids,
                self.playlists.queue_3,
            ),
            self.retry,
        )

    def state(self) -> QueueFillState:
        """Resolve original state authority after representation reads.

        Returns:
            Original caller-owned state handle.
        """
        return legacy._state_access(self.state_path, self.state_service)

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Preserve original unchecked mapping tolerance.

        Args:
            raw: Original persisted mapping value.

        Returns:
            Original accepted mapping or no mapping.
        """
        return legacy._mapped_artist(raw)

    def resolve(
        self, recommendation: ArtistRecommendation
    ) -> SpotifyArtistCandidate | str | None:
        """Preserve original ranked facts and interaction adaptation.

        Args:
            recommendation: Original current recommendation.

        Returns:
            Original mapping, skip, quit or no-match outcome.
        """
        ranked = legacy.release_check.RankedArtist(
            key=recommendation.key,
            name=recommendation.artist,
            scrobbles=0,
            rank=recommendation.base_rank,
        )
        return legacy.release_check.resolve_spotify_artist(
            self.spotify,
            ranked,
            legacy._mapping_choice_reader(self.choice, recommendation),
            self.retry,
        )

    def top_tracks(self, artist: SpotifyArtistCandidate) -> tuple[CatalogTrack, ...]:
        """Read original ordered top tracks.

        Args:
            artist: Original accepted artist mapping.

        Returns:
            Original top tracks before window truncation.
        """
        _, tracks = legacy.new_kids.load_top_track_data(
            self.spotify, artist.spotify_id, self.retry
        )
        return tracks

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Read original liked membership.

        Args:
            tracks: Original top-track window.

        Returns:
            Original liked statuses.
        """
        return legacy._liked_statuses(self.spotify, tracks, self.retry)

    def following(self, artist: SpotifyArtistCandidate) -> bool:
        """Read and validate the original Spotify following response.

        Args:
            artist: Original accepted artist mapping.

        Returns:
            Original first follow status.
        """
        return legacy._fill_following(self.spotify, artist, self.retry)

    def follow(self, artist: SpotifyArtistCandidate) -> None:
        """Accept the original Spotify follow before mirror persistence.

        Args:
            artist: Original accepted artist mapping.
        """
        legacy._fill_follow(self.spotify, artist, self.retry)

    def persist_followed(self, artist: SpotifyArtistCandidate) -> None:
        """Retain original mirror persistence and its presentation.

        Args:
            artist: Original accepted mapping.
        """
        legacy._persist_followed_artist(artist, self.echo)

    def append(self, artist: SpotifyArtistCandidate, track: CatalogTrack) -> None:
        """Accept the original Queue marker append.

        Args:
            artist: Original accepted mapping.
            track: Original selected marker.
        """
        self.retry(
            partial(
                legacy.add_playlist_item, self.spotify, self.playlists.queue, track.uri
            ),
            f"adding {artist.name} to The Queue",
        )

    def audit(self, result: FillResult, preview: bool, selected: bool) -> None:
        """Preserve original rejection and selected-addition audit fields.

        Args:
            result: Original current outcome.
            preview: Original preview behavior.
            selected: Whether an actual or proposed addition was selected.
        """
        if not selected:
            legacy.append_event(
                self.log_path, "fill_candidate", result=asdict(result), dry_run=preview
            )
            return
        legacy.append_event(
            self.log_path,
            "fill_candidate" if preview else "artist_added",
            lastfm_artist_key=result.recommendation.key,
            result=asdict(result),
            dry_run=preview,
        )

    def present(self, result: FillResult, preview: bool) -> None:
        """Retain original text after accepted audit.

        Args:
            result: Original selected outcome.
            preview: Original preview behavior.
        """
        assert result.spotify_artist is not None and result.track is not None
        self.echo(
            f"{'Would add' if preview else 'Added'} {result.spotify_artist.name} - "
            f"{result.track.name} to The Queue."
        )

    def progress(self, done: int, total: int, message: str) -> None:
        """Retain original optional progress presentation.

        Args:
            done: Original completed count.
            total: Original maximum examined count.
            message: Original status text.
        """
        if self.callback is not None:
            self.callback(done, total, message)
