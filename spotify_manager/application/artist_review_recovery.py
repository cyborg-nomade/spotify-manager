"""Replay original journaled unfollows and queue-one promotions in effect order."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.artist_review_session import ReviewSession
from spotify_manager.domain.artist_review_selection import log_int as _log_int
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.models.your_library import YourLibraryArtist


@dataclass(frozen=True)
class QueueMove:
    """Retain the original validated pending move fields and unvalidated extras.

    Args:
        source: Original source identity.
        target: Original destination identity.
        track_id: Original selected marker identity.
        track_uri: Original selected marker URI.
        source_uris: Original complete ordered removal candidates.
        raw: Original complete durable plan, including optional display fields.
    """

    source: str
    target: str
    track_id: str
    track_uri: str
    source_uris: list[str]
    raw: dict[str, object]


def flush_unfollows(session: ReviewSession) -> None:
    """Reconcile absent artists before ordered forty-artist mutation batches.

    Args:
        session: Original current mutable invocation authority.
    """
    if not session.state.pending_unfollows:
        return
    current = {artist.spotify_id: artist for artist in session.artists}
    absent: list[str] = []
    pending: list[str] = []
    for identity in session.state.pending_unfollows:
        if identity in current:
            pending.append(identity)
        else:
            absent.append(identity)
    for identity in absent:
        _reconcile_unfollow(session, identity)
    while pending:
        batch_ids = pending[:40]
        _unfollow_batch(session, [current[identity] for identity in batch_ids])
        pending = pending[40:]


def _reconcile_unfollow(session: ReviewSession, identity: str) -> None:
    plan = session.state.pending_unfollows[identity]
    item = YourLibraryArtist(
        name=str(plan.get("artist") or identity), uri=f"spotify:artist:{identity}"
    )
    session.complete(
        item,
        _log_int(plan.get("liked_tracks", 0)),
        "auto_unfollow_reconciled",
        reason=plan.get("reason"),
    )


def _unfollow_batch(session: ReviewSession, batch: list[YourLibraryArtist]) -> None:
    session.spotify.unfollow(
        [artist.uri for artist in batch], f"unfollowing {len(batch)} zero-liked artists"
    )
    removed = {artist.spotify_id for artist in batch}
    remaining = []
    for artist in session.artists:
        if artist.spotify_id not in removed:
            remaining.append(artist)
    session.artists = remaining
    session.storage.save_artists(remaining)
    session.storage.stats(len(remaining), len(batch))
    for artist in batch:
        _complete_unfollow(session, artist)


def _complete_unfollow(session: ReviewSession, artist: YourLibraryArtist) -> None:
    plan = session.state.pending_unfollows[artist.spotify_id]
    session.complete(
        artist,
        _log_int(plan.get("liked_tracks", 0)),
        "auto_unfollow",
        reason=plan.get("reason"),
        ranked_tracks=plan.get("ranked_tracks", []),
    )
    session.interaction.echo(f"Auto-unfollowed: {artist.name}")


def flush_moves(
    session: ReviewSession, membership: Callable[[str], PlaylistMembership]
) -> None:
    """Finish original pending promotions without duplicate destination markers.

    Args:
        session: Original current mutable invocation authority.
        membership: Original caller-owned membership authority.

    Raises:
        ArtistReviewError: A pending move lacks an originally required field.
    """
    artists = {artist.spotify_id: artist for artist in session.artists}
    for identity, raw in list(session.state.pending_queue_moves.items()):
        move = _move_fields(identity, raw)
        item = artists.get(identity) or YourLibraryArtist(
            name=str(raw.get("artist") or identity), uri=f"spotify:artist:{identity}"
        )
        _append_move_target(session, item, move, membership)
        removed = _remove_move_source(session, item, move, membership)
        _complete_move(session, item, move, removed)


def _move_fields(identity: str, raw: dict[str, object]) -> QueueMove:
    source = str(raw.get("source_playlist_id") or "").strip()
    target = str(raw.get("target_playlist_id") or "").strip()
    track_id = str(raw.get("selected_track_id") or "").strip()
    track_uri = str(raw.get("selected_track_uri") or "").strip()
    source_uris = _source_uris(raw.get("source_track_uris"))
    if not all((source, target, track_id, track_uri, source_uris)):
        raise ArtistReviewError(f"Incomplete pending queue move for artist {identity}.")
    return QueueMove(source, target, track_id, track_uri, source_uris, raw)


def _source_uris(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    uris = []
    for uri in raw:
        if str(uri).strip():
            uris.append(str(uri))
    return uris


def _append_move_target(
    session: ReviewSession,
    item: YourLibraryArtist,
    move: QueueMove,
    membership: Callable[[str], PlaylistMembership],
) -> None:
    target = membership(move.target)
    if item.spotify_id in target.primary_artist_ids:
        return
    session.spotify.append(
        move.target,
        move.track_uri,
        f"adding {item.name} to queue playlist {move.target}",
    )
    target.primary_artist_ids.add(item.spotify_id)
    target.track_ids.add(move.track_id)
    target.track_uris_by_primary_artist.setdefault(item.spotify_id, []).append(
        move.track_uri
    )


def _remove_move_source(
    session: ReviewSession,
    item: YourLibraryArtist,
    move: QueueMove,
    membership: Callable[[str], PlaylistMembership],
) -> list[str]:
    source = membership(move.source)
    current = set(source.track_uris_by_primary_artist.get(item.spotify_id, []))
    removed = []
    for uri in move.source_uris:
        if uri in current:
            removed.append(uri)
    for start in range(0, len(removed), 100):
        session.spotify.remove(
            move.source,
            removed[start : start + 100],
            f"removing {item.name} from queue playlist {move.source}",
        )
    _retain_source(source, item.spotify_id, removed)
    return removed


def _retain_source(
    source: PlaylistMembership, identity: str, removed: list[str]
) -> None:
    remaining = []
    for uri in source.track_uris_by_primary_artist.get(identity, []):
        if uri not in set(removed):
            remaining.append(uri)
    if remaining:
        source.track_uris_by_primary_artist[identity] = remaining
        return
    source.track_uris_by_primary_artist.pop(identity, None)
    source.primary_artist_ids.discard(identity)


def _complete_move(
    session: ReviewSession, item: YourLibraryArtist, move: QueueMove, removed: list[str]
) -> None:
    session.complete(
        item,
        _log_int(move.raw.get("liked_tracks", 0)),
        "queue_moved",
        source_playlist_id=move.source,
        playlist_id=move.target,
        removed_track_uris=removed,
        selected_track={
            "spotify_id": move.track_id,
            "uri": move.track_uri,
            "name": move.raw.get("selected_track_name"),
        },
        release=move.raw.get("release"),
    )
    session.interaction.echo(f"Moved: {item.name} from queue 1 to queue 2")
