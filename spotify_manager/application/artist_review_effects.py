"""Explicit synchronous boundaries used by followed-artist review."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


class ReviewEvent(Protocol):
    """Build the original complete audit payload at the supplied clock boundary."""

    def __call__(self, run_id: str, name: str, **details: object) -> dict[str, object]:
        """Attach original clock and run identity to an audit decision.

        Args:
            run_id: Original invocation identity.
            name: Original audit event name.
            details: Original complete decision facts.

        Returns:
            Original audit record.
        """
        ...


@dataclass(frozen=True)
class ReviewStorage:
    """Bind ordered local reads, accepted progress and durable publications.

    Args:
        artists: Complete current followed-artist mirror.
        tracks: Complete current liked-track mirror.
        state: Load original progress and attach its persistence callback.
        cache: Initialize original metadata cache for subsequent catalog reads.
        run_id: Create the original sortable invocation identity.
        event: Build original complete timestamped audit records.
        append: Append original ordered audit records.
        save_artists: Publish original remaining followed artists.
        stats: Publish original post-unfollow statistics.
    """

    artists: Callable[[], list[YourLibraryArtist]]
    tracks: Callable[[], list[YourLibraryTrack]]
    state: Callable[[], ArtistReviewState]
    cache: Callable[[bool], None]
    run_id: Callable[[], str]
    event: ReviewEvent
    append: Callable[[list[dict[str, object]]], None]
    save_artists: Callable[[list[YourLibraryArtist]], None]
    stats: Callable[[int, int], None]


@dataclass(frozen=True)
class ReviewCatalog:
    """Supply original catalog facts using the invocation's shared metadata cache.

    Args:
        tracks: Original ranked associated tracks.
        ranked: Original ranked album/EP candidates, enriched with first tracks.
        earliest: Original chronological catalog, enriched with first tracks.
    """

    tracks: Callable[[YourLibraryArtist], list[TrackCandidate]]
    ranked: Callable[[YourLibraryArtist], list[ReleaseCandidate]]
    earliest: Callable[[YourLibraryArtist], list[ReleaseCandidate]]


@dataclass(frozen=True)
class ReviewSpotify:
    """Bind original retried Spotify reads and ordered writes.

    Args:
        membership: Complete fresh primary-credit membership for one queue.
        append: Original single-marker addition.
        remove: Original requested marker removal, retaining batch order.
        unfollow: Original forty-artist mutation boundary.
    """

    membership: Callable[[str], PlaylistMembership]
    append: Callable[[str, str, str], object]
    remove: Callable[[str, list[str], str], object]
    unfollow: Callable[[list[str], str], object]


@dataclass(frozen=True)
class ReviewInteraction:
    """Bind original visible output and optional interactive decisions.

    Args:
        echo: Original visible progress and action messages.
        progress: Original optional position/total callback.
        track: Original optional tied-track prompt.
        release: Original optional release prompt with decline availability.
    """

    echo: Callable[[str], None]
    progress: Callable[[int, int, str], None] | None
    track: Callable[[YourLibraryArtist, tuple[TrackCandidate, ...]], str] | None
    release: (
        Callable[[YourLibraryArtist, tuple[ReleaseCandidate, ...], bool], str] | None
    )
