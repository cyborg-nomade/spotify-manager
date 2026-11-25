"""Prepare the artist shortlist from the recorded and published collections."""

from functools import lru_cache
from typing import Protocol

from spotify_manager.application.listening_ports import ListeningMetadata
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_rediscovery import REDISCOVERY_LIMIT
from spotify_manager.domain.listening_rediscovery import ArtistRediscovery
from spotify_manager.domain.listening_rediscovery import ArtistRevisit
from spotify_manager.domain.listening_rediscovery import ArtistRevisitEvidence
from spotify_manager.domain.listening_rediscovery import RediscoveryDates
from spotify_manager.domain.listening_rediscovery import RediscoveryRules
from spotify_manager.domain.listening_rediscovery import RevisitAlbum
from spotify_manager.domain.listening_rediscovery import RevisitAlbumChoice
from spotify_manager.domain.listening_rediscovery import rank_rediscovery_artists
from spotify_manager.domain.listening_rediscovery import rediscovery_dates
from spotify_manager.domain.listening_values import ListeningQuery


class RediscoveryReads(Protocol):
    """Read historical listening weeks and album visits from one generation."""

    @property
    def metadata(self) -> ListeningMetadata:
        """Return source coverage and identity."""
        ...

    def rediscovery_artists(
        self, dates: RediscoveryDates
    ) -> tuple[ArtistRevisitEvidence, ...]:
        """Read all artists with historical activity and their recent counts."""
        ...

    def rediscovery_albums(
        self, query: ListeningQuery, artist_keys: tuple[str, ...]
    ) -> dict[str, list[RevisitAlbum]]:
        """Read bounded album options for the chosen artists."""
        ...


@lru_cache(maxsize=12)
def get_artist_rediscovery(
    index: RediscoveryReads,
    catalog: LibraryCatalog | None,
    query: ListeningQuery,
    rules: RediscoveryRules,
) -> ArtistRediscovery:
    """Compare past and recent artist listening on pinned sources.

    Args:
        index: Pinned recorded history.
        catalog: Optional pinned Spotify collection publication.
        query: Historical dates and timezone.
        rules: Recent horizon and thresholds.

    Returns:
        A ranked artist shortlist with historical album and publication evidence.
    """
    dates = rediscovery_dates(
        query, rules, (index.metadata.first_ms, index.metadata.last_ms)
    )
    published = _published_albums(catalog)
    snapshot = catalog.snapshot if catalog else None
    if not dates.recent_complete:
        return ArtistRediscovery(dates, rules, snapshot, published is not None, 0, ())
    ranked = rank_rediscovery_artists(index.rediscovery_artists(dates), rules)
    selected = ranked[:REDISCOVERY_LIMIT]
    albums = index.rediscovery_albums(
        dates.historical, tuple(row.key for row in selected)
    )
    artists = []
    for row in selected:
        artists.append(_artist(row, albums.get(row.key, []), published or {}))
    return ArtistRediscovery(
        dates, rules, snapshot, published is not None, len(ranked), tuple(artists)
    )


@lru_cache(maxsize=4)
def _published_albums(
    catalog: LibraryCatalog | None,
) -> dict[str, dict[str, LibraryEntry]] | None:
    if catalog is None:
        return None
    sources = {item.kind: item.state for item in catalog.sources}
    if sources.get("album") != "ready":
        return None
    matches: dict[str, dict[str, LibraryEntry]] = {}
    for entry in catalog.entries:
        if entry.kind == "album":
            matches.setdefault(entry.key, {})[entry.uri] = entry
    return matches


def _artist(
    evidence: ArtistRevisitEvidence,
    albums: list[RevisitAlbum],
    published: dict[str, dict[str, LibraryEntry]],
) -> ArtistRevisit:
    result = []
    for album in albums:
        editions = published.get(album.key, {})
        exact = next(iter(editions.values())) if len(editions) == 1 else None
        result.append(RevisitAlbumChoice(album, len(editions), exact))
    return ArtistRevisit(evidence, tuple(result))
