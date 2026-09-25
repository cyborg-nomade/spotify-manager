"""Bind supplied clients, paths, and callbacks to listening integration ports."""

from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import AuditWriter
from spotify_manager.application.ports.listening import ListeningHistory
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.music import AlbumCatalog
from spotify_manager.application.ports.music import PlaylistAccess
from spotify_manager.application.ports.music import TrackMembership
from spotify_manager.infrastructure.legacy.history import ExportListeningHistory
from spotify_manager.infrastructure.legacy.spotify import RequeuePlaylistAccess
from spotify_manager.infrastructure.legacy.spotify import SpotifyAlbumCatalog
from spotify_manager.infrastructure.legacy.spotify import SpotifyTrackMembership
from spotify_manager.routines import requeue_for_a_dream


def album_review_ports(client: Spotify) -> tuple[AlbumCatalog, TrackMembership]:
    """Share an existing client across catalog and membership reads.

    Args:
        client: Caller-owned synchronous client with its existing authentication.

    Returns:
        Explicit ports for the read-only album use case; no client is created.
    """
    return SpotifyAlbumCatalog(client), SpotifyTrackMembership(client)


def requeue_playlist(client: Spotify, retry: RetryCall) -> PlaylistAccess:
    """Bind the original Requeue transport and caller-selected retry policy.

    Args:
        client: Existing synchronous client.
        retry: Unchanged retry callback owned by the invoking interface.

    Returns:
        Playlist access with no added caching, retries, or resource lifetime.
    """
    return RequeuePlaylistAccess(client, retry)


def requeue_audit(
    path: Path,
) -> AuditWriter[requeue_for_a_dream.RequeueForADreamSummary]:
    """Bind the existing JSONL writer without changing record bytes or timing.

    Args:
        path: Explicit audit destination.

    Returns:
        A writer for the unchanged Requeue summary and error semantics.
    """
    return partial(_write_requeue_audit, path)


def _write_requeue_audit(
    path: Path, summary: requeue_for_a_dream.RequeueForADreamSummary
) -> None:
    requeue_for_a_dream._append_log(summary, path)


def listening_history(path: Path) -> ListeningHistory:
    """Bind the current Last.fm loader to an explicit export path.

    Args:
        path: Export location, with the original compressed-file fallbacks.

    Returns:
        Parsed listening history, loaded only when the caller requests it.
    """
    return ExportListeningHistory(path)
