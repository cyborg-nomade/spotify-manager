"""Search Spotify for operator review without automatic qualification filters."""

from dataclasses import dataclass

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import Cancellation
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import name_similarity
from spotify_manager.infrastructure.history_matching_records import artist_names


def _query(scrobble: Scrobble) -> str:
    parts = []
    for part in (scrobble.artist, scrobble.track, scrobble.album):
        if part and part.strip():
            parts.append(part.strip())
    return " ".join(parts)


def _album(raw: dict[str, object]) -> str:
    album = raw.get("album")
    return str(album.get("name") or "").strip() if isinstance(album, dict) else ""


def _candidate(scrobble: Scrobble, raw: object, rank: int) -> SpotifyTrackMatch | None:
    if not isinstance(raw, dict):
        return None
    identifier = str(raw.get("id") or "").strip()
    title = str(raw.get("name") or "").strip()
    artists = artist_names(raw)
    if not identifier or not title or not artists:
        return None
    album = _album(raw)
    popularity = raw.get("popularity")
    return SpotifyTrackMatch(
        spotify_id=identifier,
        uri=str(raw.get("uri") or f"spotify:track:{identifier}"),
        track=title,
        artists=artists,
        album=album,
        search_rank=rank,
        track_similarity=name_similarity(scrobble.track, title),
        album_similarity=name_similarity(scrobble.album, album)
        if scrobble.album
        else None,
        popularity=popularity if isinstance(popularity, int) else None,
    )


def _candidates(response: object, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
    tracks = response.get("tracks") if isinstance(response, dict) else None
    items = tracks.get("items") if isinstance(tracks, dict) else None
    if not isinstance(items, list):
        raise SpotifyTrackResolutionError(
            "Spotify returned invalid manual search data."
        )
    candidates = []
    for rank, raw in enumerate(items[:10], start=1):
        candidate = _candidate(scrobble, raw, rank)
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


@dataclass(frozen=True)
class SpotifyManualTracks:
    """Own broad track searches under the invocation's retry and cancellation policy.

    Args:
        client: Caller-owned Spotify client.
        retry: Caller-owned retry attempt policy.
        cancellation: Invocation cancellation boundary.
    """

    client: SpotifyClient
    retry: Retry
    cancellation: Cancellation

    async def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Return up to ten results for the available historical display text.

        Args:
            scrobble: Play whose automatic resolution failed.

        Returns:
            Complete candidates in search order, without similarity filtering.

        Raises:
            SpotifyTrackResolutionError: Spotify returns a malformed search page.
            BlastFromPastCancelledError: Cancellation is requested.
        """
        self.cancellation.check()
        query = _query(scrobble)
        for attempt in self.retry.attempts(
            "searching Spotify for a manual track match"
        ):
            async with attempt:
                response = await self.client.search(
                    q=query, type="track", limit=10, offset=0
                )
        self.cancellation.check()
        return _candidates(response, scrobble)
