"""Search albums directly or expose albums from broad track search results."""

from dataclasses import dataclass

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.manual_matching import ManualAlbumCandidate
from spotify_manager.infrastructure.album_recommendations import positive_int
from spotify_manager.infrastructure.manual_track_catalog import search_text


def _artist_credits(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    result = []
    for artist in raw:
        if not isinstance(artist, dict):
            continue
        name = str(artist.get("name") or "").strip()
        if name:
            result.append((str(artist.get("id") or "").strip(), name))
    return tuple(result)


def _candidate(
    raw: object, rank: int, track_search: bool
) -> ManualAlbumCandidate | None:
    if not isinstance(raw, dict):
        return None
    album = raw.get("album") if track_search else raw
    if not isinstance(album, dict):
        return None
    identifier = str(album.get("id") or "").strip()
    title = str(album.get("name") or "").strip()
    artist_credits = _artist_credits(album.get("artists"))
    if not identifier or not title or not artist_credits:
        return None
    return ManualAlbumCandidate(
        identifier,
        f"spotify:album:{identifier}",
        title,
        tuple(name for _, name in artist_credits),
        tuple(identity for identity, _ in artist_credits),
        str(album.get("album_type") or ""),
        str(album.get("release_date") or "Unknown"),
        positive_int(album.get("total_tracks")),
        rank,
        str(raw.get("name") or "") if track_search else "",
        str(raw.get("id") or "") if track_search else "",
    )


def _candidates(
    response: object, track_search: bool
) -> tuple[ManualAlbumCandidate, ...]:
    key = "tracks" if track_search else "albums"
    page = response.get(key) if isinstance(response, dict) else None
    items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(items, list):
        raise SpotifyTrackResolutionError(
            "Spotify returned invalid manual album search data."
        )
    result = []
    seen: set[str] = set()
    for rank, raw in enumerate(items[:10], start=1):
        candidate = _candidate(raw, rank, track_search)
        if candidate is not None and candidate.spotify_id not in seen:
            result.append(candidate)
            seen.add(candidate.spotify_id)
    return tuple(result)


@dataclass(frozen=True)
class SpotifyManualAlbums:
    """Own unfiltered release searches under the invocation's request policy.

    Args:
        client: Caller-owned Spotify client.
        retry: Caller-owned retry attempts.
        cancellation: Invocation cancellation boundary.
    """

    client: SpotifyClient
    retry: Retry
    cancellation: Cancellation

    async def search(self, scrobble: Scrobble) -> tuple[ManualAlbumCandidate, ...]:
        """Present albums from the first ten results without similarity filtering.

        Args:
            scrobble: Available historical artist, track and album text.

        Returns:
            Usable distinct albums in first-encounter order.

        Raises:
            SpotifyTrackResolutionError: Search response is malformed.
            RuntimeError: Invocation cancellation is requested.
        """
        self.cancellation.check()
        track_search = bool(scrobble.track and not scrobble.album)
        kind = "track" if track_search else "album"
        for attempt in self.retry.attempts(
            "searching Spotify for a manual album match"
        ):
            async with attempt:
                response = await self.client.search(
                    q=search_text(scrobble), type=kind, limit=10, offset=0
                )
        self.cancellation.check()
        return _candidates(response, track_search)
