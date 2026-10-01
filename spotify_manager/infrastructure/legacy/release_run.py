"""Bind release stages to the original synchronous SDK, state and callback seams."""

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import PlaylistSnapshot
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import release_check as legacy


@dataclass(frozen=True)
class LegacyReleaseRun:
    """Retain caller-owned clients and the original public compatibility seams.

    Args:
        spotify: Caller-owned synchronous Spotify client.
        playlists: Original destination configuration.
        state: Acquired original state handle.
        log_path: Original release audit location.
        artist_reader: Optional original artist-choice callback.
        progress_reader: Optional original progress callback.
        retry: Original outer retry policy.
    """

    spotify: Spotify
    playlists: legacy.ReleaseCheckPlaylists
    state: RoutineState
    log_path: Path
    artist_reader: legacy.ArtistChoiceReader | None
    progress_reader: legacy.ProgressCallback | None
    retry: legacy.RetryCall

    def clock(self) -> datetime:
        """Observe the original final successful-check clock.

        Returns:
            Original current UTC timestamp.
        """
        return legacy.datetime.now(UTC)

    def persist(self, state: ReleaseState) -> None:
        """Accept the original complete checkpoint and freshness timestamp.

        Args:
            state: Complete mutable working or preview-learning state.
        """
        legacy._persist_state(self.state, state)

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Accept original event bytes and insertion-ordered fields.

        Args:
            run_id: Durable original run identity.
            event: Original event name.
            details: Original event fields.
        """
        legacy.append_event(self.log_path, run_id, event, **details)

    def progress(self, done: int, total: int, message: str) -> None:
        """Forward original progress only when a callback is supplied.

        Args:
            done: Completed artist count.
            total: Original ranked artist count.
            message: Original user-visible stage text.
        """
        if self.progress_reader is not None:
            self.progress_reader(done, total, message)

    def wine(self) -> PlaylistSnapshot:
        """Load original Wine Cellar membership before cleanup.

        Returns:
            Original ordered snapshot and membership indexes.
        """
        return legacy._playlist_snapshot(
            self.spotify, self.playlists.wine_cellar, self.retry
        )

    def cleanup(
        self, snapshot: PlaylistSnapshot, preview: bool
    ) -> tuple[int, PlaylistMembership]:
        """Retain original cleanup writes and membership projection.

        Args:
            snapshot: Original observed Wine Cellar snapshot.
            preview: Original preview mode.

        Returns:
            Planned or accepted duplicate count and cleaned membership.
        """
        return legacy._deduplicate_wine_cellar(
            self.spotify, self.playlists.wine_cellar, snapshot, preview, self.retry
        )

    def vintage(self) -> PlaylistMembership:
        """Load original New Vintage membership after Wine Cellar cleanup.

        Returns:
            Original mutable membership indexes.
        """
        return legacy._playlist_membership(
            self.spotify, self.playlists.new_vintage, self.retry
        )

    def composers(self) -> tuple[OwnedPlaylist, ...]:
        """Observe owned composer playlists, retaining original error translation.

        Returns:
            Original owned playlists excluding both destinations.

        Raises:
            ReleaseCheckSpotifyError: Original composer lookup failed.
        """
        excluded = frozenset({self.playlists.wine_cellar, self.playlists.new_vintage})
        try:
            return composer_playlists.load_owned_playlists(
                self.spotify, self.retry, excluded
            )
        except composer_playlists.ComposerPlaylistError as exc:
            raise ReleaseCheckSpotifyError(str(exc)) from exc

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Retain original persisted mapping decoding.

        Args:
            raw: Original untrusted stored mapping.

        Returns:
            Original mapping or no valid mapping.
        """
        return legacy._mapped_artist(raw)

    def resolve(self, artist: RankedArtist) -> SpotifyArtistCandidate | str | None:
        """Retain original artist interaction and synchronous search seam.

        Args:
            artist: Original frozen ranked artist.

        Returns:
            Original mapping, control choice or no search result.
        """
        return legacy.resolve_spotify_artist(
            self.spotify, artist, self.artist_reader, self.retry
        )

    def catalog(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate, start: date
    ) -> tuple[ReleaseCandidate, ...]:
        """Observe the original catalog after artist exclusions.

        Args:
            artist: Original frozen ranked artist.
            mapped: Original accepted Spotify mapping.
            start: Inclusive original window start.

        Returns:
            Original ordered catalog observations.
        """
        return legacy.load_recent_catalog(
            self.spotify, artist, mapped, start, self.retry
        )

    def decode_pending(self, raw: object) -> PendingSingle | None:
        """Retain original pending-single decoding.

        Args:
            raw: Original untrusted retained single.

        Returns:
            Original pending single or no valid record.
        """
        return legacy._pending_single(raw)

    def first_track(self, release: ReleaseCandidate) -> ReleaseTrack | None:
        """Observe the first original playable release marker.

        Args:
            release: Original reviewed release.

        Returns:
            First original playable marker or no track.
        """
        tracks = legacy.load_release_tracks(
            self.spotify, release, self.retry, first_only=True
        )
        return tracks[0] if tracks else None

    def match(
        self,
        track: ReleaseTrack,
        records: tuple[ReleaseCandidate, ...],
        cache: dict[str, tuple[ReleaseTrack, ...]],
    ) -> ReleaseCandidate | None:
        """Retain ordered containing-record matching and the original shared cache.

        Args:
            track: Original single marker.
            records: Original ordered candidate records.
            cache: Original per-artist track cache.

        Returns:
            Original first containing record or no match.
        """
        return legacy.matching_future_release(
            self.spotify, track, records, self.retry, cache
        )

    def add(
        self,
        destination: str,
        membership: PlaylistMembership,
        track: ReleaseTrack,
        preview: bool,
    ) -> PlaylistAction:
        """Retain original duplicate checks, accepted writes and membership updates.

        Args:
            destination: Original playlist identity.
            membership: Original mutable destination membership.
            track: Selected original marker.
            preview: Original preview mode.

        Returns:
            Original planned or accepted playlist action.
        """
        return legacy._add_to_playlist(
            self.spotify, destination, membership, track, preview, self.retry
        )
