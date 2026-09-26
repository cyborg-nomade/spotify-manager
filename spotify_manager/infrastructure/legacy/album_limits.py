"""Bind album-review effects to their original parsers and persistence helpers."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.artist_follows import ArtistPersistenceResult
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.library import AlbumArtist
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

    def resolve(self, album: YourLibraryAlbum) -> AlbumArtist | None:
        """Resolve a primary artist using the existing cache and metadata rules.

        Args:
            album: Current review item.

        Returns:
            Resolved artist when available.
        """
        return legacy.resolve_album_artist(self.spotify, album, self.known_artists)

    def followed(self, artist: AlbumArtist) -> bool:
        """Read current membership through the existing error translation.

        Args:
            artist: Resolved identity.

        Returns:
            Current membership.
        """
        return legacy._is_artist_followed(self.spotify, artist)

    def follow(self, artist: AlbumArtist) -> None:
        """Follow the resolved artist through the existing error translation.

        Args:
            artist: Resolved identity.
        """
        legacy._follow_artist(self.spotify, artist)

    def record(self, artist: AlbumArtist) -> ArtistPersistenceResult:
        """Publish the original artist mirror and statistics updates.

        Args:
            artist: Resolved identity.

        Returns:
            Original persistence result.
        """
        return legacy.record_followed_artist(artist)


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
    state: RoutineState
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
        echo: Existing output sink used by effect helpers and retries.
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
    echo: Callable[[str], None]
    log_path: Path
    decisions_path: Path
    state_service: StateService | None
    sleep: Callable[[float], None]
    retry_delay: int
    max_attempts: int
    _loaded: ReviewSession | None = field(default=None, init=False)

    def _session(self) -> ReviewSession:
        assert self._loaded is not None
        return self._loaded

    def _retry[T](self, operation: Callable[[], T], description: str) -> T:
        return legacy.retry_spotify_server_errors(
            operation,
            description,
            self.echo,
            self.sleep,
            self.retry_delay,
            self.max_attempts,
        )

    def albums(self) -> list[YourLibraryAlbum]:
        """Load files and decisions in their original order.

        Returns:
            Original review items, retaining duplicate entries.
        """
        albums = legacy.load_total_albums_new_file()
        library = legacy.load_your_library_file()
        remaining = list(albums)
        state = legacy._state_access(self.decisions_path, self.state_service)
        decisions = state.load()
        self._loaded = ReviewSession(
            library,
            remaining,
            state,
            decisions,
            legacy.known_artist_ids_by_name(library),
        )
        return albums

    def previously_kept(self, album: YourLibraryAlbum) -> bool:
        """Read a persisted keep choice.

        Args:
            album: Current item.

        Returns:
            Whether the original keep marker is present.
        """
        return legacy.has_persisted_keep_decision(album, self._session().decisions)

    def follow_artist(self, album: YourLibraryAlbum) -> bool:
        """Retain follow, mirror, statistics, and retry boundaries.

        Args:
            album: Current item.

        Returns:
            Whether the artist was followed.
        """
        session = self._session()
        operation = partial(
            legacy.ensure_artist_followed,
            self.spotify,
            album,
            session.known_artists,
            session.checked_artists,
            self.echo,
        )
        return self._retry(
            operation,
            f"checking/following artist for {legacy.format_album_label(album)}",
        )

    def evaluate(self, album: YourLibraryAlbum) -> AlbumEvaluation:
        """Evaluate against the loaded export with the original cache options.

        Args:
            album: Current item.

        Returns:
            Original assessment model.
        """
        operation = partial(
            legacy.evaluate_album,
            sp=self.spotify,
            album_id=album.spotify_id,
            library=self._session().library,
            threshold=self.threshold,
            use_cache=self.use_cache,
            refresh_cache=self.refresh_cache,
        )
        return self._retry(operation, f"evaluating {legacy.format_album_label(album)}")

    def live_likes(self, album: YourLibraryAlbum, track_ids: list[str]) -> int:
        """Read live membership without changing batching or retry behavior.

        Args:
            album: Current item used in retry descriptions.
            track_ids: Original ordered identifiers.

        Returns:
            Count of truthy statuses.
        """
        operation = partial(legacy.get_live_liked_track_count, self.spotify, track_ids)
        return self._retry(
            operation,
            f"checking live liked tracks for {legacy.format_album_label(album)}",
        )

    def remove(
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
        session = self._session()
        operation = partial(
            legacy.remove_album_from_library,
            self.spotify,
            album,
            evaluation,
            session.remaining,
            self.log_path,
            live_liked_tracks=live_likes,
        )
        if automatic:
            operation = partial(operation, action="auto_zero_live_likes")
        session.remaining = self._retry(
            operation, f"removing {legacy.format_album_label(album)}"
        )

    def keep(
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
        session = self._session()
        legacy.record_review_decision(
            session.decisions,
            album,
            evaluation,
            "keep",
            self.decisions_path,
            live_liked_tracks=live_likes,
            state_access=session.state,
        )
