"""Resolve the playlist source and destination before confirmation."""

from spotify_manager.application.listening_album_tracklists import AlbumTracklistReads
from spotify_manager.application.listening_album_tracklists import (
    get_rediscovery_tracklists,
)
from spotify_manager.application.listening_export import PlaylistGateway
from spotify_manager.domain.listening_export import SPOTIFY_PLAYLIST_LIMIT
from spotify_manager.domain.listening_export import ExportPlan
from spotify_manager.domain.listening_export import ExportSources
from spotify_manager.domain.listening_export import ExportTarget
from spotify_manager.domain.listening_export import ExportTrack
from spotify_manager.domain.listening_export import PlaylistExportConflictError
from spotify_manager.domain.listening_export import check_export_size
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_playlist import PlaylistPreview


class ExportSourceError(ValueError):
    """Report source choices that no longer provide a complete ordered proposal."""


def selection_export_tracks(preview: PlaylistPreview) -> tuple[ExportTrack, ...]:
    """Read the chronological preview in the already-resolved playback order.

    Args:
        preview: First-play proposal calculated from both pinned publications.

    Returns:
        Spotify tracks in their full proposal order.

    Raises:
        PlaylistExportConflictError: The preview exceeds playlist capacity.
    """
    if len(preview.tracks) > SPOTIFY_PLAYLIST_LIMIT:
        raise PlaylistExportConflictError(
            "The preview exceeds 10,000 tracks. Use a smaller selection."
        )
    tracks = []
    for row in preview.tracks:
        tracks.append(ExportTrack(row.track.uri, row.track.name, row.track.artist))
    return tuple(tracks)


async def album_export_tracks(
    catalog: LibraryCatalog,
    albums: tuple[str, ...],
    source: AlbumTracklistReads,
    *,
    first_only: bool = False,
) -> tuple[ExportTrack, ...]:
    """Verify each chosen saved album and flatten its complete tracklist in order.

    Args:
        catalog: Pinned saved album publication.
        albums: Selected Spotify album URIs in playlist order.
        source: Read-only Spotify tracklist reader.
        first_only: Use the first track in album order for the Palace queue.

    Returns:
        Full ordered album tracklists, preserving intentional repeats.

    Raises:
        ExportSourceError: An edition was repeated or a tracklist is incomplete.
    """
    if len(set(albums)) != len(albums):
        raise ExportSourceError("Choose each Spotify edition only once.")
    tracklists = await get_rediscovery_tracklists(catalog, albums, source)
    editions = {entry.uri: entry for entry in catalog.entries if entry.kind == "album"}
    tracks: list[ExportTrack] = []
    for album in tracklists.albums:
        if not album.tracks or album.message:
            raise ExportSourceError(
                "Some album tracks could not be verified. Refresh the preview."
            )
        edition = editions[album.uri]
        selected = album.tracks[:1] if first_only else album.tracks
        for track in selected:
            tracks.append(
                ExportTrack(track.uri, track.name, f"{edition.artist} — {edition.name}")
            )
    return tuple(tracks)


async def make_export_plan(
    scope: ExportSources,
    tracks: tuple[ExportTrack, ...],
    gateway: PlaylistGateway,
    identity: str | None,
    name: str,
) -> ExportPlan:
    """Bind the proposed Spotify additions to an exact owned playlist or new name.

    Args:
        scope: Both pinned publication versions.
        tracks: Exact additions in order.
        gateway: Live read-only access to the selected destination.
        identity: Existing playlist ID, if chosen.
        name: New private playlist name, if chosen.

    Returns:
        Complete immutable plan for explicit review and confirmation.

    Raises:
        ExportSourceError: An empty new playlist name was supplied.
        PlaylistExportConflictError: Destination has changed or exceeds capacity.
    """
    if identity is None and not name:
        raise ExportSourceError("Enter a name for the new playlist.")
    account = await gateway.account()
    existing = await gateway.destination(identity) if identity else None
    if existing is not None and existing.owner != account:
        raise PlaylistExportConflictError(
            "Choose a playlist owned by the signed-in Spotify account."
        )
    target = ExportTarget(existing.name if existing else name, account, existing)
    check_export_size(len(tracks), target)
    return ExportPlan(scope, target, tracks)
