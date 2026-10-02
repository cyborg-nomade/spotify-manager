"""Run-scoped artist-review facts, cached membership and durable decisions."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_effects import ReviewSpotify
from spotify_manager.application.artist_review_effects import ReviewStorage
from spotify_manager.application.artist_review_values import ArtistReviewState
from spotify_manager.application.artist_review_values import ArtistReviewSummary
from spotify_manager.application.artist_review_values import ReviewCounts
from spotify_manager.application.artist_review_values import summary_from_counts
from spotify_manager.domain.artist_review_selection import normalize_name
from spotify_manager.domain.artist_review_selection import queue_check_order
from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.domain.artist_review_values import QueuePlaylists
from spotify_manager.models.your_library import YourLibraryArtist


@dataclass
class ReviewSession:
    """Retain original invocation state, counts and lazy membership authority.

    Args:
        artists: Original mutable current followed-artist list.
        liked_counts: Original normalized liked counts.
        liked_ids: Original complete liked-track identities.
        state: Original mutable completed and pending decisions.
        run_id: Original invocation identity.
        playlists: Original three queue destinations.
        storage: Original local persistence boundaries.
        catalog: Original complete catalog reads.
        spotify: Original retried live operations.
        interaction: Original prompts and presentation.
        counts: Original mutable invocation counters.
        playlist_cache: Original once-per-invocation membership cache.
        summary_total: Original recovered-plus-pending invocation total.
    """

    artists: list[YourLibraryArtist]
    liked_counts: Counter[str]
    liked_ids: set[str]
    state: ArtistReviewState
    run_id: str
    playlists: QueuePlaylists
    storage: ReviewStorage
    catalog: ReviewCatalog
    spotify: ReviewSpotify
    interaction: ReviewInteraction
    counts: ReviewCounts = field(default_factory=ReviewCounts)
    playlist_cache: dict[str, PlaylistMembership] = field(default_factory=dict)
    summary_total: int = 0

    def membership(self, playlist_id: str) -> PlaylistMembership:
        """Retain the original lazy once-per-invocation membership read.

        Args:
            playlist_id: Original queue identity.

        Returns:
            Original mutable cached membership.
        """
        if playlist_id not in self.playlist_cache:
            self.playlist_cache[playlist_id] = self.spotify.membership(playlist_id)
        return self.playlist_cache[playlist_id]

    def placement(
        self, artist_id: str, liked_count: int
    ) -> tuple[str, str | None, bool]:
        """Retain existing queues or plan the original one-to-two promotion.

        Args:
            artist_id: Original reviewed identity.
            liked_count: Original current liked count.

        Returns:
            Target, optional move source and whether placement is complete.
        """
        queues = (
            self.playlists.queue_1,
            self.playlists.queue_2,
            self.playlists.queue_3,
        )
        for existing in queue_check_order(queues, liked_count):
            if artist_id not in self.membership(existing).primary_artist_ids:
                continue
            if existing == self.playlists.queue_1 and liked_count >= 6:
                return self.playlists.queue_2, self.playlists.queue_1, False
            return existing, None, True
        return self.playlists.for_liked_count(liked_count), None, False

    def audit(self, name: str, **details: object) -> dict[str, object]:
        """Append an original complete audit event before its state effect.

        Args:
            name: Original audit event name.
            details: Original complete decision fields.

        Returns:
            Original appended event, also used as a pending decision.
        """
        event = self.storage.event(self.run_id, name, **details)
        self.storage.append([event])
        return event

    def complete(
        self,
        artist: YourLibraryArtist,
        liked_count: int,
        action: str,
        **details: object,
    ) -> None:
        """Audit, persist and count one original completed decision in that order.

        Args:
            artist: Original reviewed artist.
            liked_count: Original decision count.
            action: Original complete action category.
            details: Original complete action facts.
        """
        event = self.storage.event(
            self.run_id,
            "artist_completed",
            artist_id=artist.spotify_id,
            artist=artist.name,
            liked_tracks=liked_count,
            action=action,
            **details,
        )
        record_completion(
            self.state,
            self.counts,
            artist.spotify_id,
            action,
            event,
            self.storage.append,
        )

    def skip(self, artist: YourLibraryArtist, liked_count: int) -> None:
        """Record the original invocation-only skip without a progress checkpoint.

        Args:
            artist: Original reviewed artist.
            liked_count: Original local liked count.
        """
        self.counts.skipped += 1
        self.audit(
            "artist_skipped_run",
            artist_id=artist.spotify_id,
            artist=artist.name,
            liked_tracks=liked_count,
        )

    def summary(self, paused: bool) -> ArtistReviewSummary:
        """Freeze the original complete invocation result.

        Args:
            paused: Original interactive quit status.

        Returns:
            Original complete summary.
        """
        return summary_from_counts(self.summary_total, self.counts, paused)


def _count_action(counts: ReviewCounts, action: str) -> None:
    counts.reviewed += 1
    if action in {"auto_unfollow", "auto_unfollow_reconciled"}:
        counts.unfollowed += 1
    elif action == "queued":
        counts.queued += 1
    elif action == "queue_moved":
        counts.moved += 1
    elif action == "already_queued":
        counts.already_queued += 1
    elif action == "declined":
        counts.declined += 1
    else:
        counts.no_action += 1


def record_completion(
    state: ArtistReviewState,
    counts: ReviewCounts,
    identity: str,
    action: str,
    event: dict[str, object],
    append: Callable[[list[dict[str, object]]], None],
) -> None:
    """Audit, checkpoint and count one original complete decision in order.

    Args:
        state: Original mutable progress.
        counts: Original mutable invocation counters.
        identity: Original completed artist identity.
        action: Original action category.
        event: Complete timestamped decision from the original outer boundary.
        append: Original ordered audit writer.
    """
    append([event])
    state.completed_artist_ids.add(identity)
    state.pending_unfollows.pop(identity, None)
    state.pending_queue_moves.pop(identity, None)
    state.persist()
    _count_action(counts, action)


def liked_count(session: ReviewSession, artist: YourLibraryArtist) -> int:
    """Read the original normalized local count without altering first labels.

    Args:
        session: Current original invocation facts.
        artist: Original complete library artist.

    Returns:
        Original count, including the zero default.
    """
    return session.liked_counts[normalize_name(artist.name)]
