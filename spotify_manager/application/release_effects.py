"""Release observation and accepted-effect contracts without clients or storage."""

from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import PlaylistSnapshot
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


class ReleaseEffects(Protocol):
    """Sequential catalog, interaction, destination and checkpoint boundaries."""

    def clock(self) -> datetime:
        """Observe the final successful-check clock.

        Returns:
            Current UTC timestamp.
        """

    def progress(self, done: int, total: int, message: str) -> None:
        """Record original user-visible progress.

        Args:
            done: Completed artists.
            total: Ranked artists.
            message: Stage text.
        """

    def persist(self, state: ReleaseState) -> None:
        """Accept a complete checkpoint before a possible later failure.

        Args:
            state: Mutable working or preview-learning state.
        """

    def audit(self, run_id: str, event: str, **details: object) -> None:
        """Accept original audit fields before a possible later failure.

        Args:
            run_id: Durable identity.
            event: Event name.
            details: Ordered event fields.
        """

    def wine(self) -> PlaylistSnapshot:
        """Observe Wine Cellar before its cleanup.

        Returns:
            Original ordered snapshot.
        """

    def cleanup(
        self, snapshot: PlaylistSnapshot, preview: bool
    ) -> tuple[int, PlaylistMembership]:
        """Observe original Wine Cellar cleanup.

        Args:
            snapshot: Loaded snapshot.
            preview: Preview mode.

        Returns:
            Original cleanup count and membership.
        """

    def vintage(self) -> PlaylistMembership:
        """Observe New Vintage after Wine Cellar cleanup.

        Returns:
            Original destination membership.
        """

    def composers(self) -> tuple[OwnedPlaylist, ...]:
        """Observe owned composer playlists.

        Returns:
            Owned playlists excluding both destinations.
        """

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Observe persisted mapping decoding.

        Args:
            raw: Stored mapping or missing value.

        Returns:
            The observed previously stored mapping, when present.
        """

    def resolve(self, artist: RankedArtist) -> SpotifyArtistCandidate | str | None:
        """Observe artist interaction before catalog reads.

        Args:
            artist: Frozen ranked artist.

        Returns:
            Scenario's mapping, control choice or no match.
        """

    def catalog(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate, start: date
    ) -> tuple[ReleaseCandidate, ...]:
        """Observe the catalog after artist exclusions.

        Args:
            artist: Frozen ranked artist.
            mapped: Resolved Spotify artist.
            start: Original inclusive window start.

        Returns:
            Scenario's ordered releases.
        """

    def decode_pending(self, raw: object) -> PendingSingle | None:
        """Decode a stored retained single.

        Args:
            raw: Stored single or missing value.

        Returns:
            A valid retained marker or no valid pending record.
        """

    def first_track(self, candidate: ReleaseCandidate) -> ReleaseTrack | None:
        """Observe a playable first track before eligibility review.

        Args:
            candidate: Reviewed release.

        Returns:
            Original marker, or no playable track.
        """

    def match(
        self,
        track: ReleaseTrack,
        records: tuple[ReleaseCandidate, ...],
        cache: dict[str, tuple[ReleaseTrack, ...]],
    ) -> ReleaseCandidate | None:
        """Observe future/current matching with its run-scoped cache.

        Args:
            track: Single marker.
            records: Ordered containing-record candidates.
            cache: Shared per-artist track cache.

        Returns:
            The observed matching record, if present.
        """

    def add(
        self,
        destination: str,
        destination_membership: PlaylistMembership,
        track: ReleaseTrack,
        preview: bool,
    ) -> PlaylistAction:
        """Accept the original playlist write and update membership.

        Args:
            destination: Wine or Vintage identifier.
            destination_membership: Original mutable observed membership.
            track: Selected marker.
            preview: Preview mode.

        Returns:
            Original planned or accepted action.
        """
