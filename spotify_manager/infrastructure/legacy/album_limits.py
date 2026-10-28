"""Bind album-review effects to their original parsers and persistence helpers."""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from spotify_manager.application.artist_follows import ArtistPersistenceResult
from spotify_manager.application.artist_follows import follow_album_artist
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Wait
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.ports.state import BlockingRoutineState
from spotify_manager.application.retry_attempts import RetryAttempts
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
from spotify_manager.infrastructure.async_state import AsyncRoutineState
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.interfaces.presenters.album_limits import present_artist_follow
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.routines import review_album_limits as legacy


@dataclass
class AlbumArtistAdapter:
    """Bind artist observations to the existing review helpers.

    Args:
        spotify: Caller-owned synchronous client.
        known_artists: Artist-name resolution cache scoped to this review.
    """

    spotify: Spotify
    known_artists: dict[str, str]

    async def resolve(self, album: YourLibraryAlbum) -> AlbumArtist | None:
        """Resolve a primary artist using the existing cache and metadata rules.

        Args:
            album: Current review item.

        Returns:
            Resolved artist when available.
        """
        from spotify_manager.routines.review_album_limits import (
            async_resolve_album_artist as resolve_album_artist,
        )

        return await resolve_album_artist(self.spotify, album, self.known_artists)

    async def followed(self, artist: AlbumArtist) -> bool:
        """Read current membership through the existing error translation.

        Args:
            artist: Resolved identity.

        Returns:
            Current membership.
        """
        from spotify_manager.routines.review_album_limits import _is_artist_followed

        return await _is_artist_followed(self.spotify, artist)

    async def follow(self, artist: AlbumArtist) -> None:
        """Follow the resolved artist through the existing error translation.

        Args:
            artist: Resolved identity.
        """
        from spotify_manager.routines.review_album_limits import _follow_artist

        await _follow_artist(self.spotify, artist)

    async def record(self, artist: AlbumArtist) -> ArtistPersistenceResult:
        """Publish the original artist mirror and statistics updates.

        Args:
            artist: Resolved identity.

        Returns:
            Original persistence result.
        """
        from spotify_manager.routines.review_album_limits import (
            async_record_followed_artist as record_followed_artist,
        )

        return await record_followed_artist(artist)


@dataclass
class ReviewSession:
    """Loaded state retained for the duration of a review.

    Args:
        library: Export observations used by cached evaluations.
        remaining: Mutable mirror snapshot after successful removals.
        state: Existing namespace persistence boundary.
        decisions: Loaded keep choices.
        known_artists: Artist identities resolved during this run.
        checked_artists: Artist membership checks completed during this run.
    """

    library: YourLibraryFile
    remaining: list[YourLibraryAlbum]
    state: BlockingRoutineState
    decisions: legacy.ReviewDecisions
    known_artists: dict[str, str]
    checked_artists: set[str] = field(default_factory=set)


@dataclass
class LegacyAlbumReview:
    """Run-scoped compatibility adapter; construction performs no I/O.

    Args:
        spotify: Caller-owned synchronous client.
        threshold: Existing retention threshold.
        use_cache: Original cache-read option.
        refresh_cache: Original cache-refresh option.
        output: Existing output sink used by effect helpers and retries.
        log_path: Removal audit destination.
        decisions_path: Explicit legacy path or configured default.
        state_service: Optional shared-state service.
        sleep: Existing retry wait callback.
        retry_delay: Existing retry delay.
        max_attempts: Existing retry limit.
    """

    spotify: Spotify
    threshold: float
    use_cache: bool
    refresh_cache: bool
    output: Messages
    log_path: Path
    decisions_path: Path
    state_service: StateService | None
    sleep: Wait
    retry_delay: int
    max_attempts: int
    _loaded: ReviewSession | None = field(default=None, init=False)

    def _session(self) -> ReviewSession:
        assert self._loaded is not None
        return self._loaded

    def _attempts(self, description: str) -> RetryAttempts:
        return SpotifyRetries(
            self.output, self.sleep, self.retry_delay, self.max_attempts
        ).attempts(description)

    async def albums(self) -> list[YourLibraryAlbum]:
        """Load files and decisions in their original order.

        Returns:
            Original review items, retaining duplicate entries.
        """
        from spotify_manager.loaders_savers import load_total_albums_new_file
        from spotify_manager.loaders_savers import load_your_library_file
        from spotify_manager.routines.review_album_limits import _state_access
        from spotify_manager.routines.review_album_limits import (
            known_artist_ids_by_name,
        )

        async with blocking_capacity():
            albums_read = asyncio.create_task(
                asyncio.to_thread(load_total_albums_new_file)
            )
            albums = await finish_blocking(albums_read)
        async with blocking_capacity():
            library_read = asyncio.create_task(
                asyncio.to_thread(load_your_library_file)
            )
            library = await finish_blocking(library_read)
        remaining = list(albums)
        state = _state_access(self.decisions_path, self.state_service)
        decisions = await AsyncRoutineState(state).load()
        self._loaded = ReviewSession(
            library,
            remaining,
            state,
            decisions,
            known_artist_ids_by_name(library),
        )
        return albums

    def previously_kept(self, album: YourLibraryAlbum) -> bool:
        """Read a persisted keep choice.

        Args:
            album: Current item.

        Returns:
            Whether the original keep marker is present.
        """
        from spotify_manager.routines.review_album_limits import (
            has_persisted_keep_decision,
        )

        return has_persisted_keep_decision(album, self._session().decisions)

    async def follow_artist(self, album: YourLibraryAlbum) -> bool:
        """Retain follow, mirror, statistics, and retry boundaries.

        Args:
            album: Current item.

        Returns:
            Whether the artist was followed.
        """
        from spotify_manager.interfaces.presenters.album_limits import (
            format_album_label,
        )

        session = self._session()
        description = f"checking/following artist for {format_album_label(album)}"
        for attempt in self._attempts(description):
            async with attempt:
                return await self._follow_review_artist(
                    album, session.known_artists, session.checked_artists
                )
        raise AssertionError("Retry scopes must include an attempt")

    async def _follow_review_artist(
        self,
        album: YourLibraryAlbum,
        known_artists: dict[str, str],
        checked_artists: set[str],
    ) -> bool:
        outcome = await follow_album_artist(
            AlbumArtistAdapter(self.spotify, known_artists), album, checked_artists
        )
        present_artist_follow(outcome, album, self.output)
        return outcome.action == "followed"

    async def evaluate(self, album: YourLibraryAlbum) -> AlbumEvaluation:
        """Evaluate against the loaded export with the original cache options.

        Args:
            album: Current item.

        Returns:
            Original assessment model.
        """
        from spotify_manager.application.library_lookup_run import evaluate_local
        from spotify_manager.bootstrap.library_lookups import local_album
        from spotify_manager.interfaces.presenters.album_limits import (
            format_album_label,
        )

        access = local_album(self.spotify, None, self.use_cache, self.refresh_cache)
        library = self._session().library
        for attempt in self._attempts(f"evaluating {format_album_label(album)}"):
            async with attempt:
                return await evaluate_local(
                    access, None, album.spotify_id, None, library, self.threshold
                )
        raise AssertionError("Retry scopes must include an attempt")

    async def live_likes(self, album: YourLibraryAlbum, track_ids: list[str]) -> int:
        """Read live membership without changing batching or retry behavior.

        Args:
            album: Current item used in retry descriptions.
            track_ids: Original ordered identifiers.

        Returns:
            Count of truthy statuses.
        """
        from spotify_manager.interfaces.presenters.album_limits import (
            format_album_label,
        )
        from spotify_manager.routines.review_album_limits import (
            async_get_live_liked_track_count as get_live_liked_track_count,
        )

        description = f"checking live liked tracks for {format_album_label(album)}"
        for attempt in self._attempts(description):
            async with attempt:
                return await get_live_liked_track_count(self.spotify, track_ids)
        raise AssertionError("Retry scopes must include an attempt")

    async def remove(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
        *,
        automatic: bool,
    ) -> None:
        """Remove then persist and audit through the original effect helper.

        Args:
            album: Current item.
            evaluation: Assessment recorded in the audit.
            live_likes: Last current membership count.
            automatic: Whether zero current likes triggered the removal.
        """
        from spotify_manager.interfaces.presenters.album_limits import (
            format_album_label,
        )
        from spotify_manager.routines.review_album_limits import (
            async_remove_album_from_library as remove_album_from_library,
        )

        session = self._session()
        action = "auto_zero_live_likes" if automatic else "manual"
        for attempt in self._attempts(f"removing {format_album_label(album)}"):
            async with attempt:
                session.remaining = await remove_album_from_library(
                    self.spotify,
                    album,
                    evaluation,
                    session.remaining,
                    self.log_path,
                    action=action,
                    live_liked_tracks=live_likes,
                )

    async def keep(
        self,
        album: YourLibraryAlbum,
        evaluation: AlbumEvaluation,
        live_likes: int | None,
    ) -> None:
        """Save a keep choice at the original persistence boundary.

        Args:
            album: Current item.
            evaluation: Assessment recorded with the choice.
            live_likes: Last current membership count.
        """
        from spotify_manager.routines.review_album_limits import record_review_decision

        session = self._session()
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    record_review_decision,
                    session.decisions,
                    album,
                    evaluation,
                    "keep",
                    self.decisions_path,
                    live_liked_tracks=live_likes,
                    state_access=session.state,
                )
            )
            await finish_blocking(file_operation)
