"""Observe artist completion without coupling its business rules to Spotify."""

from typing import Protocol

from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_assessment import first_liked
from spotify_manager.domain.discovery_assessment import popular_liked_track
from spotify_manager.domain.discovery_assessment import qualification_reasons
from spotify_manager.domain.discovery_assessment import representative_track


class AssessmentCatalog(Protocol):
    """Provide the original catalog, membership and popularity observations."""

    def saved(self, ids: list[str]) -> dict[str, bool]:
        """Read saved releases using the existing batching policy.

        Args:
            ids: Catalog IDs, retaining duplicates.

        Returns:
            Accepted statuses keyed by ID.
        """

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read ordered tracks for one parsed release.

        Args:
            release: Requested catalog entry.

        Returns:
            Original playable tracks with primary credits.
        """

    def liked(self, ids: list[str], *, top: bool = False) -> dict[str, bool]:
        """Read live likes with the original context-specific retry descriptions.

        Args:
            ids: Ordered requested track IDs.
            top: Whether the read belongs to artist top tracks.

        Returns:
            Accepted memberships keyed by ID.
        """

    def top_tracks(self, artist_id: str) -> tuple[CatalogTrack, ...]:
        """Read the artist's eligible Spotify top tracks.

        Args:
            artist_id: Artist being assessed.

        Returns:
            Top tracks in the original response order.
        """

    def popularities(self, ids: list[str]) -> dict[str, int]:
        """Read fallback track popularity only when top tracks supply no liked marker.

        Args:
            ids: Unique liked primary-artist catalog IDs.

        Returns:
            Accepted live popularity observations.
        """


def assess_artist(
    access: AssessmentCatalog,
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    track_cache: dict[str, tuple[CatalogTrack, ...]],
) -> ArtistAssessment:
    """Observe completion criteria and markers at the original read boundaries.

    Args:
        access: Explicit catalog and membership integration.
        artist_id: Primary artist being assessed.
        catalog: Original ranked release observations, retaining duplicate entries.
        track_cache: Shared cache, updated only for previously unseen releases.

    Returns:
        Original completion assessment and marker choices.
    """
    saved = access.saved([release.spotify_id for release in catalog])
    tracks = _primary_tracks(access, artist_id, catalog, track_cache)
    liked = access.liked(list(tracks))
    liked_tracks = _liked_tracks(tracks, liked)
    reasons = qualification_reasons(
        catalog, saved, liked_tracks=len(liked_tracks), total_tracks=len(tracks)
    )
    representative = representative_track(artist_id, catalog, track_cache)
    top = _top_liked(access, artist_id, liked_tracks)
    return ArtistAssessment(
        liked_tracks=len(liked_tracks),
        saved_releases=sum(saved.values()),
        total_releases=len(catalog),
        liked_primary_tracks=len(liked_tracks),
        total_primary_tracks=len(tracks),
        qualifies=bool(reasons),
        reasons=reasons,
        representative_track=representative,
        top_liked_track=top,
    )


def _primary_tracks(
    access: AssessmentCatalog,
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    cache: dict[str, tuple[CatalogTrack, ...]],
) -> dict[str, CatalogTrack]:
    unique: dict[str, CatalogTrack] = {}
    for release in catalog:
        tracks = cache.get(release.spotify_id)
        if tracks is None:
            tracks = access.tracks(release)
            cache[release.spotify_id] = tracks
        _collect_primary(unique, tracks, artist_id)
    return unique


def _collect_primary(
    unique: dict[str, CatalogTrack], tracks: tuple[CatalogTrack, ...], artist_id: str
) -> None:
    for track in tracks:
        if track.primary_artist_id == artist_id:
            unique.setdefault(track.spotify_id, track)


def _liked_tracks(
    tracks: dict[str, CatalogTrack], liked: dict[str, bool]
) -> list[CatalogTrack]:
    result = []
    for spotify_id, track in tracks.items():
        if liked.get(spotify_id, False):
            result.append(track)
    return result


def _top_liked(
    access: AssessmentCatalog, artist_id: str, liked_tracks: list[CatalogTrack]
) -> CatalogTrack | None:
    tracks = access.top_tracks(artist_id)
    liked = access.liked([track.spotify_id for track in tracks], top=True)
    selected = first_liked(tracks, liked)
    if selected is not None or not liked_tracks:
        return selected
    popularities = access.popularities([track.spotify_id for track in liked_tracks])
    return popular_liked_track(liked_tracks, popularities)
