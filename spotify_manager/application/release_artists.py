"""Resolve ranked artists and preserve permanent, composer and membership exclusions."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.release_destinations import ReleaseDestinations
from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.composers import composer_playlist_candidates
from spotify_manager.domain.release_check import artist_is_present
from spotify_manager.domain.release_check_values import RankedArtist


@dataclass(frozen=True)
class ReleaseArtists:
    """Coordinate artist interaction before observing any release catalog.

    Args:
        progress: Authoritative progress and accepted checkpoint/audit effects.
        destinations: Destination membership and owned composer observations.
        mapping: Named artist-mapping application stage.
    """

    progress: ReleaseProgress
    destinations: ReleaseDestinations
    mapping: ArtistMapping

    async def resolve(
        self, artist: RankedArtist
    ) -> SpotifyArtistCandidate | Literal["quit"] | None:
        """Skip completed/excluded artists or resolve and remember their mapping.

        Args:
            artist: Original frozen ranked artist.

        Returns:
            Resolved artist, an explicit pause, or no catalog work.
        """
        if artist.key in self.progress.completed:
            return None
        if artist.key in self.progress.skipped:
            await self._complete(artist, "permanently skipped")
            return None
        self._notify(artist, "resolving Spotify artist")
        mapped: SpotifyArtistCandidate | Literal["quit"] | None = (
            self.progress.effects.decode_mapping(self.progress.mappings.get(artist.key))
        )
        if mapped is None:
            mapped = await self._interact(artist)
        if mapped == "quit" or mapped is None:
            return mapped
        if await self._excluded(artist, mapped):
            return None
        return mapped

    def _notify(self, artist: RankedArtist, message: str) -> None:
        self.progress.notify(f"#{artist.rank} {artist.name}: {message}")

    async def _complete(self, artist: RankedArtist, message: str) -> None:
        await self.progress.complete(artist)
        self._notify(artist, message)

    async def _interact(
        self, artist: RankedArtist
    ) -> SpotifyArtistCandidate | Literal["quit"] | None:
        mapped = await self.mapping.run(artist)
        if mapped == "quit":
            await self.progress.pause(artist)
            return "quit"
        if mapped == "skip-artist":
            await self.progress.skip_permanently(artist)
            return None
        if mapped is None or mapped == "skip":
            await self._skip_once(artist, mapped is None)
            return None
        assert isinstance(mapped, SpotifyArtistCandidate)
        await self.progress.remember_mapping(artist, mapped)
        return mapped

    async def _skip_once(self, artist: RankedArtist, missing: bool) -> None:
        self.progress.mark_completed(artist)
        if self.progress.preview:
            return
        await self.progress.effects.audit(
            self.progress.opening.run_id,
            "artist_skipped",
            artist=artist.name,
            reason="no Spotify search result" if missing else "interactive skip",
        )
        await self.progress.checkpoint_completed()

    async def _excluded(
        self, artist: RankedArtist, mapped: SpotifyArtistCandidate
    ) -> bool:
        matches = composer_playlist_candidates(
            mapped.name,
            self.destinations.composers,
            excluded_playlist_ids=frozenset(
                {self.destinations.wine_id, self.destinations.vintage_id}
            ),
        )
        if matches:
            await self._complete(artist, "classical composer, skipped")
            return True
        if (
            artist_is_present(self.destinations.wine, mapped)
            and not artist.is_new_vintage
        ):
            await self._complete(artist, "already in Wine Cellar")
            return True
        return False
