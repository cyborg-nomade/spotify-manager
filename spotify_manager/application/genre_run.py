"""Save a discovered genre source and copy its missing markers sequentially."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from spotify_manager.application.genre_values import GenreOutcome
from spotify_manager.domain.genres import GenrePlaylistSource
from spotify_manager.domain.genres import destination_tracks


class GenreEffects(Protocol):
    """Source, destination, accepted writes and completion boundaries."""

    def source(self, slug: str, name: str) -> GenrePlaylistSource:
        """Discover validated source metadata and original ordered markers.

        Args:
            slug: Original genre identity.
            name: Original display name.

        Returns:
            Original source observations.
        """

    def destination(self, playlist_id: str) -> frozenset[str]:
        """Observe destination membership after source discovery.

        Args:
            playlist_id: Original destination identity.

        Returns:
            Live destination track identities.
        """

    def follow(self, source: GenrePlaylistSource) -> None:
        """Save the original source playlist even when no track append is needed.

        Args:
            source: Original discovered source.
        """

    def append(self, destination: str, missing: tuple[str, ...]) -> None:
        """Accept the original ordered missing-marker append.

        Args:
            destination: Original target identity.
            missing: Original missing source markers.
        """

    def clock(self) -> datetime:
        """Read the original completion clock after accepted writes.

        Returns:
            Original current UTC time.
        """

    def audit(self, outcome: GenreOutcome) -> None:
        """Present and audit the completed original outcome.

        Args:
            outcome: Original completed source/save/copy observations.
        """


@dataclass(frozen=True)
class GenreReveal:
    """Coordinate original source discovery, membership decisions and accepted effects.

    Args:
        effects: Original sequential external boundaries.
    """

    effects: GenreEffects

    def run(self, slug: str, name: str, destination: str) -> GenreOutcome:
        """Save a genre playlist and copy only its missing source markers.

        Args:
            slug: Original genre identity.
            name: Original genre display name.
            destination: Original target playlist identity.

        Returns:
            Completed original outcome after presentation and accepted audit.
        """
        source = self.effects.source(slug, name)
        existing = self.effects.destination(destination)
        missing, present = destination_tracks(source.track_uris, existing)
        self.effects.follow(source)
        if missing:
            self.effects.append(destination, missing)
        result = GenreOutcome(
            source.preview,
            destination,
            source.track_uris,
            missing,
            present,
            self.effects.clock(),
        )
        self.effects.audit(result)
        return result
