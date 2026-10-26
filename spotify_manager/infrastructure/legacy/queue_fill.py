"""Bind Queue fill stages to the original synchronous SDK and persistence seams."""

from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime

from spotipy import Spotify

from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.runtime import ReviewProgressMessages
from spotify_manager.application.queue_fill_values import FillResult
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar
from spotify_manager.infrastructure.recommendation_history import refresh_history
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.queue_fill import QueueFillResources
from spotify_manager.routines import the_queue as legacy


@dataclass
class LegacyQueueFill:
    """Bind application stages to caller-owned clients and storage.

    Args:
        spotify: Caller-owned spotify.
        lastfm: Caller-owned lastfm.
        options: Caller-owned options.
        callbacks: Caller-owned callbacks.
        resources: Caller-owned resources.
        retry: Effective request retry resolved at the original validation boundary.
    """

    spotify: Spotify
    lastfm: legacy.LastFmReader
    options: QueueFillOptions
    callbacks: QueueFillCallbacks
    resources: QueueFillResources
    retry: legacy.RetryCall = NoRetry()

    def configure(self) -> None:
        """Resolve original falsey retry behavior after request validation."""
        self.retry = self.callbacks.retry_call or NoRetry()

    def clock(self) -> datetime:
        """Resolve the original effective timestamp.

        Returns:
            Original supplied or current time converted to UTC.
        """
        return (self.options.now or datetime.now(UTC)).astimezone(UTC)

    def local_date(self, now: datetime) -> date:
        """Resolve the original local listening calendar.

        Args:
            now: Original effective timestamp.

        Returns:
            Original effective listening week.
        """
        return BerlinCalendar().local_date(now)

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
        progress = (
            ReviewProgressMessages(self)
            if self.callbacks.progress_callback is not None
            else None
        )
        try:
            return refresh_history(
                self.lastfm,
                export_path=self.resources.export_path,
                recent_path=self.resources.recent_path,
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
        from spotify_manager.routines.new_wine import load_playlist_tracks

        return len(
            load_playlist_tracks(self.spotify, self.options.playlists.queue, self.retry)
        )

    def search(
        self, artist: RankedArtist, text: str | None
    ) -> tuple[SpotifyArtistCandidate, ...]:
        """Read original artist candidates using the configured retry boundary.

        Args:
            artist: Original ranked Last.fm evidence.
            text: Optional explicit custom query.

        Returns:
            Original ordered Spotify artist candidates.
        """
        from spotify_manager.routines.release_check import search_spotify_artists

        return search_spotify_artists(self.spotify, artist, self.retry, text)

    def represented(self) -> set[str]:
        """Retain original destination read order before state loading.

        Returns:
            Original represented Spotify artist identities.
        """
        from spotify_manager.routines.the_queue import _playlist_artist_ids

        return _playlist_artist_ids(
            self.spotify,
            (
                self.options.playlists.queue,
                self.options.playlists.queue_2,
                self.options.playlists.new_kids,
                self.options.playlists.queue_3,
            ),
            self.retry,
        )

    def state(self) -> QueueStateAccess:
        """Resolve original state authority after representation reads.

        Returns:
            Original caller-owned state handle.
        """
        from spotify_manager.routines.the_queue import _state_access

        return _state_access(self.resources.state_path, self.resources.state_service)

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Preserve original unchecked mapping tolerance.

        Args:
            raw: Original persisted mapping value.

        Returns:
            Original accepted mapping or no mapping.
        """
        from spotify_manager.routines.the_queue import _mapped_artist

        return _mapped_artist(raw)

    def top_tracks(self, artist: SpotifyArtistCandidate) -> tuple[CatalogTrack, ...]:
        """Read original ordered top tracks.

        Args:
            artist: Original accepted artist mapping.

        Returns:
            Original top tracks before window truncation.
        """
        from spotify_manager.routines.new_kids import load_top_track_data

        _, tracks = load_top_track_data(self.spotify, artist.spotify_id, self.retry)
        return tracks

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Read original liked membership.

        Args:
            tracks: Original top-track window.

        Returns:
            Original liked statuses.
        """
        from spotify_manager.routines.the_queue import _liked_statuses

        return _liked_statuses(self.spotify, tracks, self.retry)

    def following(self, artist: SpotifyArtistCandidate) -> bool:
        """Read and validate the original Spotify following response.

        Args:
            artist: Original accepted artist mapping.

        Returns:
            Original first follow status.
        """
        from spotify_manager.routines.the_queue import _fill_following

        return _fill_following(self.spotify, artist, self.retry)

    def follow(self, artist: SpotifyArtistCandidate) -> None:
        """Accept the original Spotify follow before mirror persistence.

        Args:
            artist: Original accepted artist mapping.
        """
        from spotify_manager.routines.the_queue import _fill_follow

        _fill_follow(self.spotify, artist, self.retry)

    def persist_followed(self, artist: SpotifyArtistCandidate) -> None:
        """Retain original mirror persistence and its presentation.

        Args:
            artist: Original accepted mapping.
        """
        from spotify_manager.routines.the_queue import _persist_followed_artist

        _persist_followed_artist(artist, self.callbacks.output)

    def append(self, artist: SpotifyArtistCandidate, track: CatalogTrack) -> None:
        """Accept the original Queue marker append.

        Args:
            artist: Original accepted mapping.
            track: Original selected marker.
        """
        from spotify_manager.routines.review_artists import add_playlist_item

        for attempt in self.retry.attempts(f"adding {artist.name} to The Queue"):
            with attempt:
                add_playlist_item(self.spotify, self.options.playlists.queue, track.uri)

    def audit(self, result: FillResult, preview: bool, selected: bool) -> None:
        """Preserve original rejection and selected-addition audit fields.

        Args:
            result: Original current outcome.
            preview: Original preview behavior.
            selected: Whether an actual or proposed addition was selected.
        """
        from spotify_manager.routines.the_queue import append_event

        if not selected:
            append_event(
                self.resources.log_path,
                "fill_candidate",
                result=asdict(result),
                dry_run=preview,
            )
            return
        append_event(
            self.resources.log_path,
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
        self.callbacks.output.echo(
            f"{('Would add' if preview else 'Added')} {result.spotify_artist.name}"
            f" - {result.track.name} to The Queue."
        )

    def progress(self, done: int, total: int, message: str) -> None:
        """Retain original optional progress presentation.

        Args:
            done: Original completed count.
            total: Original maximum examined count.
            message: Original status text.
        """
        if self.callbacks.progress_callback is not None:
            self.callbacks.progress_callback.progress(done, total, message)
