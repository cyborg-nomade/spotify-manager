"""Typed ordered boundaries required by The Queue's fill business rules."""

from collections.abc import Sequence
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.application.queue_fill_values import FillResult
from spotify_manager.application.queue_state import QueueStateAccess
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble


class QueueFillEffects(Protocol):
    """Original reads, interaction, accepted writes, audit and presentation seams."""

    def configure(self) -> None:
        """Resolve the original retry boundary after request validation."""

    def clock(self) -> datetime:
        """Resolve the original UTC timestamp.

        Returns:
            Original effective timestamp.
        """

    def local_date(self, now: datetime) -> date:
        """Resolve the original local listening calendar.

        Args:
            now: Original effective timestamp.

        Returns:
            Original effective listening week.
        """

    async def history(
        self, preview: bool, now: datetime
    ) -> tuple[Sequence[Scrobble], int]:
        """Refresh original history with unchanged preview behavior.

        Args:
            preview: Original history preview mode.
            now: Original effective timestamp.

        Returns:
            Original refreshed plays and live additions.
        """

    async def queue_length(self) -> int:
        """Read original Queue membership after refreshing history.

        Returns:
            Original observed Queue length.
        """

    async def represented(self) -> set[str]:
        """Read original representation destinations before state loading.

        Returns:
            Original represented Spotify artist identities.
        """

    def state(self) -> QueueStateAccess:
        """Resolve the original state access boundary.

        Returns:
            Caller-owned state reader and accepted checkpoint writer.
        """

    def decode_mapping(self, raw: object) -> SpotifyArtistCandidate | None:
        """Decode original persisted mapping tolerance.

        Args:
            raw: Original unchecked mapping.

        Returns:
            Original mapping or no mapping.
        """

    async def top_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[CatalogTrack, ...]:
        """Read original artist top tracks.

        Args:
            artist: Original accepted artist mapping.

        Returns:
            Original ordered top tracks.
        """

    async def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Read original liked membership for the selected window.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original liked statuses.
        """

    async def following(self, artist: SpotifyArtistCandidate) -> bool:
        """Read and validate original artist follow status.

        Args:
            artist: Original accepted mapping.

        Returns:
            Original observed follow status.
        """

    async def follow(self, artist: SpotifyArtistCandidate) -> None:
        """Accept the original follow before local persistence.

        Args:
            artist: Original accepted mapping.
        """

    async def persist_followed(self, artist: SpotifyArtistCandidate) -> None:
        """Persist original artist mirrors after an accepted follow.

        Args:
            artist: Original accepted mapping.
        """

    async def append(self, artist: SpotifyArtistCandidate, track: CatalogTrack) -> None:
        """Accept the original Queue append after following when needed.

        Args:
            artist: Original accepted mapping.
            track: Original selected Queue marker.
        """

    async def audit(self, result: FillResult, preview: bool, selected: bool) -> None:
        """Accept original completion or rejection fields.

        Args:
            result: Original ordered candidate outcome.
            preview: Original preview behavior.
            selected: Whether this is an actual or proposed addition.
        """

    def present(self, result: FillResult, preview: bool) -> None:
        """Present original addition text after accepted audit.

        Args:
            result: Original actual or proposed addition.
            preview: Original preview behavior.
        """

    def progress(self, done: int, total: int, message: str) -> None:
        """Present original resolution progress.

        Args:
            done: Original completed candidate count.
            total: Original maximum examined candidates.
            message: Original resolution text.
        """
