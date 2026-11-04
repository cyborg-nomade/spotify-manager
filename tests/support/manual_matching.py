"""Typed scripted catalogs and explicit operator choices for matching checks."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.manual_matching import ManualAlbumCandidate


@dataclass
class CatalogChoices:
    """Own ordered explicit choices and the invocation's cancellation checkpoints.

    Args:
        answers: Accepted IDs or empty strings, consumed in order.
        offered: Complete offered observations in interaction order.
        checks: Observed cancellation checkpoints.
        cancel_at: Checkpoint that requests cancellation, or zero to continue.
    """

    answers: list[str] = field(default_factory=list)
    offered: list[tuple[Scrobble, tuple[str, ...]]] = field(default_factory=list)
    checks: int = 0
    cancel_at: int = 0

    def check(self) -> None:
        """Stop at the configured cancellation checkpoint.

        Raises:
            BlastFromPastCancelledError: The scripted checkpoint is reached.
        """
        self.checks += 1
        if self.checks == self.cancel_at:
            raise BlastFromPastCancelledError("Matching cancelled")

    async def choose(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> str:
        """Consume one track decision without selecting by similarity.

        Args:
            scrobble: Historical reference being matched.
            candidates: Offered unfiltered track observations.

        Returns:
            Scripted identity or explicit rejection.
        """
        self.offered.append((scrobble, tuple(item.spotify_id for item in candidates)))
        return self.answers.pop(0)

    async def choose_album_match(
        self, scrobble: Scrobble, candidates: tuple[ManualAlbumCandidate, ...]
    ) -> str:
        """Consume one album decision in the original catalog order.

        Args:
            scrobble: Historical reference being matched.
            candidates: Offered album observations.

        Returns:
            Scripted identity or explicit rejection.
        """
        self.offered.append((scrobble, tuple(item.spotify_id for item in candidates)))
        return self.answers.pop(0)


@dataclass(frozen=True)
class TrackSearch:
    """Return a complete scripted track search page.

    Args:
        candidates: Unfiltered track observations in search order.
    """

    candidates: tuple[SpotifyTrackMatch, ...] = ()

    async def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Return the scripted search results.

        Args:
            scrobble: Original historical reference.

        Returns:
            Unfiltered track results.
        """
        return self.candidates


@dataclass(frozen=True)
class AlbumSearch:
    """Return a complete scripted album search page.

    Args:
        candidates: Unfiltered album observations in search order.
    """

    candidates: tuple[ManualAlbumCandidate, ...] = ()

    async def search(self, scrobble: Scrobble) -> tuple[ManualAlbumCandidate, ...]:
        """Return the scripted album results.

        Args:
            scrobble: Original historical reference.

        Returns:
            Unfiltered album results.
        """
        return self.candidates


def album_candidate(
    identity: str = "album", kind: str = "album"
) -> ManualAlbumCandidate:
    """Build a complete operator-visible release with two credited artists.

    Args:
        identity: Album identity.
        kind: Spotify release type before eligibility decisions.

    Returns:
        Complete unfiltered album observation.
    """
    return ManualAlbumCandidate(
        identity,
        f"spotify:album:{identity}",
        "Different album",
        ("New", "Guest"),
        ("new", "guest"),
        kind,
        "2025-01-01",
        10,
        1,
        "Matched song",
        "source-track",
    )
