"""Retain genre discovery, SDK writes and presentation at the outer boundary."""

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotify_manager.application.genre_values import GenreOutcome
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.genres import GenrePlaylistSource
from spotify_manager.domain.genres import GenreSource
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.genre_pages import GenrePages
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.routines import genre_reveal as legacy


@dataclass
class LegacyGenreReveal:
    """Bind the original source reader, Spotify client and completed audit seam.

    Args:
        spotify: Caller-owned Spotify client.
        pages: Named public-page reader.
        path: Original audit location.

    Attributes:
        result: Accepted legacy result, populated after a successful run.
    """

    spotify: Spotify
    pages: GenrePages
    path: Path
    result: legacy.GenreRevealRunResult = field(init=False)

    async def source(self, slug: str, name: str) -> GenrePlaylistSource:
        """Discover the original source before reading destination membership.

        Args:
            slug: Original validated genre identity.
            name: Original validated display name.

        Returns:
            Typed original public links and ordered markers.
        """
        from spotify_manager.routines.genre_reveal import _load_genre_playlist_source

        source = await _load_genre_playlist_source(slug, name, self.pages)
        preview = source.preview
        values = GenreSource(
            preview.slug,
            preview.name,
            preview.every_noise_url,
            preview.source_playlist_id,
            preview.source_playlist_uri,
            preview.source_playlist_url,
        )
        return GenrePlaylistSource(values, source.track_uris)

    async def destination(self, playlist_id: str) -> frozenset[str]:
        """Retain original playlist membership observation.

        Args:
            playlist_id: Original destination identity.

        Returns:
            Original live destination identities.
        """
        from spotify_manager.routines.blast_from_past import (
            async_load_playlist_state as load_playlist_state,
        )

        return (await load_playlist_state(self.spotify, playlist_id)).track_ids

    async def follow(self, source: GenrePlaylistSource) -> None:
        """Accept the original library-save request before any marker append.

        Args:
            source: Discovered original source.
        """
        from spotify_manager.routines.genre_reveal import _save_source_playlist

        await _save_source_playlist(self.spotify, source)

    async def append(self, destination: str, missing: tuple[str, ...]) -> None:
        """Accept the original ordered missing-marker append.

        Args:
            destination: Original target identity.
            missing: Original missing markers.
        """
        from spotify_manager.routines.genre_reveal import _append_source_tracks

        await _append_source_tracks(self.spotify, destination, missing)

    def clock(self) -> datetime:
        """Retain the original completion clock after accepted writes.

        Returns:
            Original current UTC time.
        """
        return legacy.datetime.now(UTC)

    async def audit(self, outcome: GenreOutcome) -> None:
        """Construct the original presented result before accepting its audit.

        Args:
            outcome: Completed original business observations.
        """
        from spotify_manager.routines.genre_reveal import (
            append_genre_reveal_log as _append_genre_reveal_log,
        )

        self.result = legacy.GenreRevealRunResult(
            **asdict(outcome.source),
            destination_playlist_id=outcome.destination_playlist_id,
            source_track_uris=list(outcome.source_track_uris),
            added_track_uris=list(outcome.added_track_uris),
            already_present_track_uris=list(outcome.already_present_track_uris),
            completed_at=outcome.completed_at,
        )
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(_append_genre_reveal_log, self.result, self.path)
            )
            await finish_blocking(file_operation)
