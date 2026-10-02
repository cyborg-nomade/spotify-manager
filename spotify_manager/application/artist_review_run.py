"""Open, recover, review and complete one original followed-artist invocation."""

from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass

from spotify_manager.application.artist_review_decisions import review_artist
from spotify_manager.application.artist_review_effects import ReviewCatalog
from spotify_manager.application.artist_review_effects import ReviewInteraction
from spotify_manager.application.artist_review_effects import ReviewSpotify
from spotify_manager.application.artist_review_effects import ReviewStorage
from spotify_manager.application.artist_review_recovery import flush_moves
from spotify_manager.application.artist_review_recovery import flush_unfollows
from spotify_manager.application.artist_review_session import ReviewSession
from spotify_manager.application.artist_review_session import liked_count
from spotify_manager.application.artist_review_values import ArtistReviewSummary
from spotify_manager.domain.artist_review_selection import normalize_name
from spotify_manager.domain.artist_review_values import QueuePlaylists
from spotify_manager.models.your_library import YourLibraryArtist


@dataclass(frozen=True)
class ArtistReview:
    """Coordinate original decisions through independently supplied boundaries.

    Args:
        playlists: Original three queue identities.
        storage: Ordered file and durable progress boundaries.
        catalog: Complete original catalog reads.
        spotify: Original retried live effects.
        interaction: Original output and optional decision readers.
    """

    playlists: QueuePlaylists
    storage: ReviewStorage
    catalog: ReviewCatalog
    spotify: ReviewSpotify
    interaction: ReviewInteraction

    def run(
        self, refresh_cache: bool = False, limit: int | None = None
    ) -> ArtistReviewSummary:
        """Preserve recovery-before-review and quit-before-final-progress ordering.

        Args:
            refresh_cache: Original metadata cache reset option.
            limit: Original pending-list slicing, including zero and negatives.

        Returns:
            Original complete or paused invocation summary.
        """
        session = self._open(refresh_cache)
        _started(session)
        _recover(session)
        pending = _pending(session, limit)
        session.summary_total = session.counts.reviewed + len(pending)
        for position, artist in enumerate(pending, start=1):
            _present(session, artist, position, len(pending))
            if not review_artist(session, artist):
                return _finish(session, len(pending), True)
        return _finish(session, len(pending), False)

    def _open(self, refresh_cache: bool) -> ReviewSession:
        artists = self.storage.artists()
        tracks = self.storage.tracks()
        counts = Counter(normalize_name(track.artist) for track in tracks)
        identities = {track.spotify_id for track in tracks}
        state = self.storage.state()
        self.storage.cache(refresh_cache)
        identity = self.storage.run_id()
        return ReviewSession(
            artists,
            counts,
            identities,
            state,
            identity,
            self.playlists,
            self.storage,
            self.catalog,
            self.spotify,
            self.interaction,
        )


def _started(session: ReviewSession) -> None:
    session.audit(
        "review_started",
        artists=len(session.artists),
        liked_tracks=sum(session.liked_counts.values()),
        pending_unfollows=len(session.state.pending_unfollows),
        pending_queue_moves=len(session.state.pending_queue_moves),
    )


def _recover(session: ReviewSession) -> None:
    flush_unfollows(session)
    flush_moves(session, session.membership)


def _pending(session: ReviewSession, limit: int | None) -> list[YourLibraryArtist]:
    pending = []
    for artist in session.artists:
        if artist.spotify_id not in session.state.completed_artist_ids:
            pending.append(artist)
    return pending if limit is None else pending[:limit]


def _present(
    session: ReviewSession, artist: YourLibraryArtist, position: int, total: int
) -> None:
    count = liked_count(session, artist)
    if session.interaction.progress is not None:
        session.interaction.progress(position - 1, total, artist.name)
    session.interaction.echo(
        f"[{position}/{total}] {artist.name}: "
        f"{count} liked track{'s' if count != 1 else ''}"
    )


def _finish(session: ReviewSession, total: int, paused: bool) -> ArtistReviewSummary:
    _recover(session)
    if paused:
        session.audit("review_paused")
        return session.summary(True)
    if session.interaction.progress is not None:
        session.interaction.progress(total, total, "Complete")
    session.audit("review_completed", summary=asdict(session.summary(False)))
    return session.summary(False)
