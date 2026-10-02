"""Original artist-statistics and cached/offline album lookup workflows."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.lookup_effects import CachedTracks
from spotify_manager.application.lookup_effects import LocalAlbumLookup
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain import albums as album_policy
from spotify_manager.domain.lookup_selection import local_album
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import AlbumTrackLikedStatus
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile


@dataclass(frozen=True)
class ArtistStatistics:
    """Supply original identity, catalog and membership stages.

    Args:
        resolve: Original exact identity resolution.
        releases: Original primary-credit release gathering.
        saved: Original saved-release membership count.
        tracks: Original primary-credit track gathering.
        liked: Original liked-track membership count.
    """

    resolve: Callable[[], tuple[str, str]]
    releases: Callable[[str], list[str]]
    saved: Callable[[list[str]], int]
    tracks: Callable[[str, list[str]], list[str]]
    liked: Callable[[list[str]], int]


def artist_statistics(deps: ArtistStatistics) -> ArtistLibraryStats:
    """Observe release membership before gathering and checking track facts.

    Args:
        deps: Original explicitly injected lookup stages.

    Returns:
        Original live artist-statistics response.
    """
    identifier, name = deps.resolve()
    releases = deps.releases(identifier)
    saved = deps.saved(releases)
    tracks = deps.tracks(identifier, releases)
    liked = deps.liked(tracks)
    return ArtistLibraryStats(
        artist_name=name,
        artist_id=identifier,
        liked_tracks=liked,
        saved_releases=saved,
        source="spotify-live",
    )


def count_contains(
    ids: list[str],
    contains: Callable[[list[str]], object],
    resource: str,
    batch_size: int,
) -> int:
    """Count original truthy statuses without changing ordered batch requests.

    Args:
        ids: Original catalog identities.
        contains: Original membership request.
        resource: Original visible resource label.
        batch_size: Original conservative batch size.

    Returns:
        Original count of truthy membership values.

    Raises:
        SpotifyLookupResponseError: Original shape or count validation fails.
    """
    count = 0
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        response = contains(batch)
        if not isinstance(response, list) or len(response) != len(batch):
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid {resource} statuses."
            )
        count += sum(bool(saved) for saved in response)
    return count


def tracklist(
    deps: CachedTracks, identifier: str, use_cache: bool, refresh_cache: bool
) -> tuple[list[LookupTrack], bool]:
    """Retain authoritative empty hits and delayed client acquisition.

    Args:
        deps: Original unchecked cache and delayed fetch boundaries.
        identifier: Original requested album identity.
        use_cache: Original cache-read/publication flag.
        refresh_cache: Original bypass-hit flag.

    Returns:
        Original complete tracks and cache-hit flag.
    """
    cache = deps.load() if use_cache else {}
    if use_cache and not refresh_cache and identifier in cache:
        return cache[identifier], True
    tracks = deps.fetch(identifier)
    if use_cache:
        cache[identifier] = tracks
        deps.save(cache)
    return tracks, False


def evaluate_local(
    deps: LocalAlbumLookup,
    name: str | None,
    identifier: str | None,
    artist: str | None,
    library: YourLibraryFile | None,
    threshold: float,
) -> AlbumEvaluation:
    """Resolve original local facts before the optional cached/live track read.

    Args:
        deps: Original export and track boundaries.
        name: Original optional exact album name.
        identifier: Original direct identity taking precedence.
        artist: Original optional primary-artist constraint.
        library: Original caller-supplied export or none.
        threshold: Original retention proportion.

    Returns:
        Original album evaluation response.
    """
    facts = library if library is not None else deps.library()
    resolved_id, resolved_name, resolved_artist = local_album(
        facts.albums, name, identifier, artist
    )
    liked_ids = {track.spotify_id for track in facts.tracks}
    tracks, cached = deps.tracks(resolved_id)
    statuses, liked = local_statuses(tracks, liked_ids)
    return local_evaluation(
        resolved_id, resolved_name, resolved_artist, statuses, liked, threshold, cached
    )


def local_statuses(
    tracks: list[LookupTrack], liked_ids: set[str]
) -> tuple[list[AlbumTrackLikedStatus], int]:
    """Validate original cached rows one at a time after identity membership.

    Args:
        tracks: Original unchecked minimized/cache records.
        liked_ids: Original export membership authority.

    Returns:
        Original status models and raw liked count.
    """
    statuses = []
    liked_count = 0
    for track in tracks:
        liked = track.get("id") in liked_ids
        liked_count += int(liked)
        statuses.append(
            AlbumTrackLikedStatus(
                name=track["name"],
                uri=track["uri"],
                liked=liked,
                spotify_id=track.get("id"),
            )
        )
    return statuses, liked_count


def local_evaluation(
    identifier: str,
    name: str | None,
    artist: str | None,
    statuses: list[AlbumTrackLikedStatus],
    liked: int,
    threshold: float,
    cached: bool,
) -> AlbumEvaluation:
    """Apply the original pure keep rule after status-model validation.

    Args:
        identifier: Original resolved identity.
        name: Original optional local display name.
        artist: Original optional local artist.
        statuses: Original validated ordered tracks.
        liked: Original raw liked count.
        threshold: Original keep proportion.
        cached: Original cache-hit flag.

    Returns:
        Original complete album evaluation model.
    """
    assessment = album_policy.assess_album(len(statuses), liked, threshold)
    return AlbumEvaluation(
        album_name=name or identifier,
        album_id=identifier,
        artist_name=artist,
        total_tracks=len(statuses),
        liked_tracks=liked,
        required_liked_tracks=assessment.required_liked_tracks,
        liked_ratio=assessment.liked_ratio,
        threshold=threshold,
        decision=assessment.decision,
        tracks=statuses,
        source="files" if cached else "files+api",
        from_cache=cached,
    )
