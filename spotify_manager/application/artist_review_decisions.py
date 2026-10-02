"""Coordinate original zero-liked, track-tier and release-tier artist decisions."""

from dataclasses import asdict

from spotify_manager.application.artist_review_recovery import flush_moves
from spotify_manager.application.artist_review_recovery import flush_unfollows
from spotify_manager.application.artist_review_session import ReviewSession
from spotify_manager.application.artist_review_session import liked_count
from spotify_manager.domain.artist_review_selection import ambiguous_track_choices
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import InvalidReviewChoiceError
from spotify_manager.domain.artist_review_values import PlaylistMembership
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.models.your_library import YourLibraryArtist


def review_artist(session: ReviewSession, artist: YourLibraryArtist) -> bool:
    """Execute one original decision, returning false only on an interactive quit.

    Args:
        session: Current original invocation facts and boundaries.
        artist: Original pending followed artist.

    Returns:
        Whether the original pending-artist loop should continue.

    Raises:
        ArtistReviewError: An original marker or choice cannot be applied safely.
    """
    count = liked_count(session, artist)
    if count == 0:
        _zero_liked(session, artist)
        return True
    target, source, complete = session.placement(artist.spotify_id, count)
    membership = session.membership(target)
    if complete:
        _already_queued(session, artist, count, target)
        return True
    if target == session.playlists.queue_1:
        return _review_track(session, artist, count, target, membership)
    return _review_release(session, artist, count, target, source, membership)


def _zero_liked(session: ReviewSession, artist: YourLibraryArtist) -> None:
    tracks = session.catalog.tracks(artist)[:5]
    primary = any(track.primary_artist_id == artist.spotify_id for track in tracks)
    if tracks and primary:
        session.complete(
            artist,
            0,
            "kept_primary_top_track",
            ranked_tracks=[asdict(track) for track in tracks],
        )
        session.interaction.echo(
            f"Kept: {artist.name} has a primary-credited ranked track"
        )
        return
    reason = "no_ranked_tracks" if not tracks else "no_primary_top_track"
    plan = session.audit(
        "unfollow_planned",
        artist_id=artist.spotify_id,
        artist=artist.name,
        liked_tracks=0,
        reason=reason,
        ranked_tracks=[asdict(track) for track in tracks],
    )
    session.state.pending_unfollows[artist.spotify_id] = plan
    session.state.persist()
    session.interaction.echo(f"Planned automatic unfollow: {artist.name} ({reason})")
    if len(session.state.pending_unfollows) >= 40:
        flush_unfollows(session)


def _already_queued(
    session: ReviewSession, artist: YourLibraryArtist, count: int, target: str
) -> None:
    session.complete(
        artist,
        count,
        "already_queued",
        playlist_id=target,
        expected_playlist_id=session.playlists.for_liked_count(count),
        placement="retained_existing_tier",
    )
    session.interaction.echo(f"Already queued: {artist.name}")


def _primary_unliked(
    session: ReviewSession, artist: YourLibraryArtist
) -> list[TrackCandidate]:
    eligible = []
    for track in session.catalog.tracks(artist):
        if (
            track.primary_artist_id == artist.spotify_id
            and track.spotify_id not in session.liked_ids
        ):
            eligible.append(track)
    return ambiguous_track_choices(eligible)


def _review_track(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    target: str,
    membership: PlaylistMembership,
) -> bool:
    choices = _primary_unliked(session, artist)
    if not choices:
        session.complete(artist, count, "no_unliked_primary_track")
        session.interaction.echo(
            f"No unliked primary-credited ranked track: {artist.name}"
        )
        return True
    if len(choices) == 1:
        _queue_track(session, artist, count, target, membership, choices[0], True)
        return True
    reader = session.interaction.track
    choice = (
        reader(artist, tuple(choices)) if reader is not None else choices[0].spotify_id
    )
    control = _control_choice(session, artist, count, choice)
    if control is not None:
        return control
    selected = _selected_track(artist, choices, choice)
    _queue_track(session, artist, count, target, membership, selected, False)
    return True


def _control_choice(
    session: ReviewSession, artist: YourLibraryArtist, count: int, choice: str
) -> bool | None:
    if choice == "quit":
        return False
    if choice == "skip":
        session.skip(artist, count)
        return True
    return None


def _selected_track(
    artist: YourLibraryArtist, choices: list[TrackCandidate], choice: str
) -> TrackCandidate:
    for track in choices:
        if track.spotify_id == choice:
            return track
    raise InvalidReviewChoiceError(f"Unknown track choice for {artist.name}: {choice}")


def _queue_track(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    target: str,
    membership: PlaylistMembership,
    track: TrackCandidate,
    automatic: bool,
) -> None:
    session.spotify.append(target, track.uri, f"adding {track.name} to queue playlist")
    membership.track_ids.add(track.spotify_id)
    membership.primary_artist_ids.add(artist.spotify_id)
    membership.track_uris_by_primary_artist.setdefault(artist.spotify_id, []).append(
        track.uri
    )
    session.complete(
        artist,
        count,
        "queued",
        playlist_id=target,
        track=asdict(track),
        selection="automatic" if automatic else "prompted",
    )
    session.interaction.echo(f"Queued: {artist.name} - {track.name}")


def _review_release(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    target: str,
    source: str | None,
    membership: PlaylistMembership,
) -> bool:
    decline = target == session.playlists.queue_3
    releases = (
        session.catalog.earliest(artist) if decline else session.catalog.ranked(artist)
    )
    eligible = _eligible_releases(releases, artist.spotify_id)
    if not eligible:
        _no_release(session, artist, count, releases)
        return True
    reader = session.interaction.release
    choice = (
        reader(artist, tuple(releases), decline)
        if reader is not None
        else eligible[0].spotify_id
    )
    control = _control_choice(session, artist, count, choice)
    if control is not None:
        return control
    if choice == "decline":
        _decline(session, artist, count, releases, decline)
        return True
    selected = _selected_release(artist, eligible, choice)
    if source is not None:
        _plan_move(session, artist, count, source, target, selected)
        return True
    _queue_release(session, artist, count, target, membership, selected)
    return True


def _eligible_releases(
    releases: list[ReleaseCandidate], artist_id: str
) -> list[ReleaseCandidate]:
    eligible = []
    for release in releases:
        if release.is_eligible_for(artist_id):
            eligible.append(release)
    return eligible


def _no_release(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    releases: list[ReleaseCandidate],
) -> None:
    session.complete(
        artist,
        count,
        "no_eligible_release",
        releases=[asdict(release) for release in releases],
    )
    session.interaction.echo(f"No eligible first-track release: {artist.name}")


def _decline(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    releases: list[ReleaseCandidate],
    allowed: bool,
) -> None:
    if not allowed:
        raise InvalidReviewChoiceError(f"Decline is not available for {artist.name}.")
    session.complete(
        artist, count, "declined", releases=[asdict(release) for release in releases]
    )
    session.interaction.echo(f"Declined queue addition: {artist.name}")


def _selected_release(
    artist: YourLibraryArtist, releases: list[ReleaseCandidate], choice: str
) -> ReleaseCandidate:
    selected = next(
        (release for release in releases if release.spotify_id == choice), None
    )
    if selected is None or not selected.first_track_uri:
        raise InvalidReviewChoiceError(
            f"Unknown or ineligible release choice for {artist.name}: {choice}"
        )
    return selected


def _plan_move(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    source: str,
    target: str,
    release: ReleaseCandidate,
) -> None:
    uris = list(
        session.membership(source).track_uris_by_primary_artist.get(
            artist.spotify_id, []
        )
    )
    if not uris:
        raise ArtistReviewError(
            f"Cannot safely move {artist.name}: its queue-1 track URI "
            "was not returned by Spotify."
        )
    if not release.first_track_id:
        raise ArtistReviewError(
            f"Cannot safely move {artist.name}: the selected track has no ID."
        )
    plan = session.audit(
        "queue_move_planned",
        artist_id=artist.spotify_id,
        artist=artist.name,
        liked_tracks=count,
        source_playlist_id=source,
        target_playlist_id=target,
        source_track_uris=uris,
        selected_track_id=release.first_track_id,
        selected_track_uri=release.first_track_uri,
        selected_track_name=release.first_track_name,
        release=asdict(release),
    )
    session.state.pending_queue_moves[artist.spotify_id] = plan
    session.state.persist()
    flush_moves(session, session.membership)


def _queue_release(
    session: ReviewSession,
    artist: YourLibraryArtist,
    count: int,
    target: str,
    membership: PlaylistMembership,
    release: ReleaseCandidate,
) -> None:
    assert release.first_track_uri is not None
    session.spotify.append(
        target,
        release.first_track_uri,
        f"adding {release.first_track_name} to queue playlist",
    )
    if release.first_track_id:
        membership.track_ids.add(release.first_track_id)
    membership.primary_artist_ids.add(artist.spotify_id)
    membership.track_uris_by_primary_artist.setdefault(artist.spotify_id, []).append(
        release.first_track_uri
    )
    session.complete(
        artist,
        count,
        "queued",
        playlist_id=target,
        release=asdict(release),
        selection="prompted",
    )
    session.interaction.echo(
        f"Queued: {artist.name} - {release.first_track_name} ({release.name})"
    )
