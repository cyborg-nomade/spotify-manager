"""Advance the first Requeue for a Dream artist to their next studio release."""

import json
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Literal

from spotipy import Spotify

# UFI
from spotify_manager.routines import new_wine
from spotify_manager.routines import slow_listening


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_LOG_PATH = FILES_DIR / "requeue_for_a_dream_log.jsonl"
RetryCall = Callable[[Callable[[], object], str], object]
Echo = Callable[[str], None]
ProgressCallback = Callable[[str], None]
RequeueAction = Literal["advance", "drop", "empty", "skip"]


class RequeueForADreamError(RuntimeError):
    """Base error for Requeue for a Dream flushes."""


class RequeueForADreamConfigError(RequeueForADreamError):
    """Raised when the playlist setting is missing or invalid."""


class RequeueForADreamChangedError(RequeueForADreamError):
    """Raised when the playlist head changes before a real mutation."""


class RequeueForADreamLogError(RequeueForADreamError):
    """Raised when a completed real transition cannot be logged."""


@dataclass(frozen=True)
class RequeueForADreamSummary:
    """Outcome of one playlist-head transition."""

    recorded_at: datetime
    playlist_id: str
    dry_run: bool
    action: RequeueAction
    playlist_length_before: int
    playlist_length_after: int
    artist: str | None = None
    source_track: str | None = None
    source_release: str | None = None
    target_track: str | None = None
    target_release: str | None = None
    target_release_type: str | None = None
    target_release_date: str | None = None
    target_already_present: bool = False
    reason: str | None = None


def parse_playlist_id(reference: str | None) -> str:
    """Extract the configured Requeue for a Dream playlist id."""
    try:
        return new_wine.parse_playlist_id(
            reference,
            "REQEUEUE_FOR_A_DREAM_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        raise RequeueForADreamConfigError(str(exc)) from exc


def _next_release(
    source: new_wine.PlaylistTrack,
    discography: tuple[slow_listening.DiscographyRelease, ...],
) -> slow_listening.DiscographyRelease | None:
    """Return the release after the source edition's canonical identity."""
    source_identity = slow_listening.release_identity(source.release.name)
    current_index = next(
        (
            index
            for index, release in enumerate(discography)
            if release.identity == source_identity
        ),
        None,
    )
    if current_index is None or current_index + 1 >= len(discography):
        return None
    return discography[current_index + 1]


def _add_track(
    spotify: Spotify,
    playlist_id: str,
    track: new_wine.ReleaseTrack,
    retry_call: RetryCall,
) -> None:
    """Append the replacement before the source is removed."""
    retry_call(
        lambda: spotify._post(
            f"playlists/{playlist_id}/items",
            payload={"uris": [track.uri]},
        ),
        f"adding {track.name} to Requeue for a Dream",
    )


def _remove_track(
    spotify: Spotify,
    playlist_id: str,
    track: new_wine.PlaylistTrack,
    retry_call: RetryCall,
) -> None:
    """Remove the old playlist marker after its replacement is secure."""
    retry_call(
        lambda: spotify._delete(
            f"playlists/{playlist_id}/items",
            payload={"items": [{"uri": track.uri}]},
        ),
        f"removing {track.name} from Requeue for a Dream",
    )


def _append_log(summary: RequeueForADreamSummary, path: Path) -> None:
    """Append one completed real transition to the review log."""
    record = asdict(summary)
    record["recorded_at"] = summary.recorded_at.isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise RequeueForADreamLogError(
            f"Could not write Requeue for a Dream log: {path}"
        ) from exc


def _summary(
    playlist_id: str,
    dry_run: bool,
    action: RequeueAction,
    before: int,
    after: int,
    *,
    source: new_wine.PlaylistTrack | None = None,
    target: new_wine.ReleaseTrack | None = None,
    target_release: slow_listening.DiscographyRelease | None = None,
    target_already_present: bool = False,
    reason: str | None = None,
) -> RequeueForADreamSummary:
    """Build a consistent result for mutation and no-op paths."""
    return RequeueForADreamSummary(
        recorded_at=datetime.now(UTC),
        playlist_id=playlist_id,
        dry_run=dry_run,
        action=action,
        playlist_length_before=before,
        playlist_length_after=after,
        artist=source.primary_artist_name if source else None,
        source_track=source.name if source else None,
        source_release=source.release.name if source else None,
        target_track=target.name if target else None,
        target_release=target_release.name if target_release else None,
        target_release_type=(target_release.release_type if target_release else None),
        target_release_date=(
            target_release.chronology_date if target_release else None
        ),
        target_already_present=target_already_present,
        reason=reason,
    )


def flush_requeue_for_a_dream(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool = False,
    echo: Echo = print,
    progress_callback: ProgressCallback | None = None,
    retry_call: RetryCall | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
) -> RequeueForADreamSummary:
    """Replace the playlist head with the next release's first track."""
    retry = retry_call or (lambda operation, _description: operation())
    if progress_callback is not None:
        progress_callback("Loading Requeue for a Dream")
    try:
        playlist = new_wine.load_playlist_tracks(spotify, playlist_id, retry)
    except new_wine.NewWineError as exc:
        raise RequeueForADreamError(str(exc)) from exc
    before = len(playlist)
    if not playlist:
        return _summary(
            playlist_id,
            dry_run,
            "empty",
            0,
            0,
            reason="playlist is empty",
        )

    source = playlist[0]
    if progress_callback is not None:
        progress_callback(f"Loading {source.primary_artist_name}'s discography")
    try:
        discography = slow_listening.load_discography(
            spotify,
            source.primary_artist_id,
            retry,
        )
    except slow_listening.SlowListeningError as exc:
        raise RequeueForADreamError(str(exc)) from exc

    source_identity = slow_listening.release_identity(source.release.name)
    current_release = next(
        (release for release in discography if release.identity == source_identity),
        None,
    )
    if current_release is None:
        summary = _summary(
            playlist_id,
            dry_run,
            "skip",
            before,
            before,
            source=source,
            reason="current release is not an eligible studio album or EP",
        )
        if not dry_run:
            _append_log(summary, log_path)
        return summary

    target_release = _next_release(source, discography)
    target: new_wine.ReleaseTrack | None = None
    target_already_present = False
    action: RequeueAction = "drop"
    after = before - 1
    if target_release is not None:
        if progress_callback is not None:
            progress_callback(f"Loading {target_release.name}")
        try:
            target_tracks = slow_listening.load_release_tracks(
                spotify,
                target_release,
                retry,
            )
        except slow_listening.SlowListeningError as exc:
            raise RequeueForADreamError(str(exc)) from exc
        if not target_tracks:
            summary = _summary(
                playlist_id,
                dry_run,
                "skip",
                before,
                before,
                source=source,
                target_release=target_release,
                reason="next release has no playable tracks",
            )
            if not dry_run:
                _append_log(summary, log_path)
            return summary
        target = target_tracks[0]
        target_already_present = any(
            track.spotify_id == target.spotify_id for track in playlist
        )
        action = "advance"
        after = before - int(target_already_present)

    if not dry_run:
        if progress_callback is not None:
            progress_callback("Rechecking the playlist head")
        try:
            current_playlist = new_wine.load_playlist_tracks(
                spotify,
                playlist_id,
                retry,
            )
        except new_wine.NewWineError as exc:
            raise RequeueForADreamError(str(exc)) from exc
        if not current_playlist or current_playlist[0].spotify_id != source.spotify_id:
            raise RequeueForADreamChangedError(
                "Requeue for a Dream changed before the update; nothing was changed."
            )

        if target is not None and not target_already_present:
            _add_track(spotify, playlist_id, target, retry)
            echo(
                f"Added {target.name} "
                f"({target_release.name if target_release else 'unknown release'})."
            )
        elif target is not None:
            echo(f"{target.name} is already present; it was not duplicated.")
        _remove_track(spotify, playlist_id, source, retry)
        echo(f"Removed {source.name} ({source.release.name}).")

    reason = "last eligible release" if action == "drop" else None
    summary = _summary(
        playlist_id,
        dry_run,
        action,
        before,
        after,
        source=source,
        target=target,
        target_release=target_release,
        target_already_present=target_already_present,
        reason=reason,
    )
    if not dry_run:
        _append_log(summary, log_path)
    return summary
