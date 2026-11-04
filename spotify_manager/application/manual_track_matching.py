"""Resolve an unqualified historical play through an explicit operator choice."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch


class ManualTrackCatalog(Protocol):
    """Read Spotify's unfiltered track search results."""

    async def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Search the available artist, track and album text.

        Args:
            scrobble: Historical play requiring manual resolution.

        Returns:
            Up to ten usable results in Spotify search order.
        """
        ...


class TrackMatchInteraction(Protocol):
    """Present manual candidates and accept a selection or explicit rejection."""

    async def choose(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> str:
        """Choose a candidate, reject all results, or raise on cancellation.

        Args:
            scrobble: Original historical play.
            candidates: Unfiltered candidates in search order, possibly empty.

        Returns:
            Selected Spotify ID, or an empty string for no match.
        """
        ...


@dataclass(frozen=True)
class ManualTrackMatching:
    """Search and validate explicit choices without automatic similarity gates.

    Args:
        catalog: Broad Spotify track search resource.
        interaction: Operator choice owner.
        cancellation: Invocation cancellation boundary.
    """

    catalog: ManualTrackCatalog
    interaction: TrackMatchInteraction
    cancellation: Cancellation

    async def run(self, scrobble: Scrobble) -> SpotifyTrackMatch | None:
        """Resolve one play without applying automatic ranking to manual results.

        Args:
            scrobble: Play for which automatic matching failed.

        Returns:
            Explicitly selected track, or none when rejected.

        Raises:
            SpotifyTrackResolutionError: A choice is outside the offered candidates.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        self.cancellation.check()
        candidates = await self.catalog.search(scrobble)
        self.cancellation.check()
        selected = await self.interaction.choose(scrobble, candidates)
        self.cancellation.check()
        if not selected:
            return None
        for candidate in candidates:
            if candidate.spotify_id == selected:
                return candidate
        raise SpotifyTrackResolutionError("The selected Spotify track is not offered.")
