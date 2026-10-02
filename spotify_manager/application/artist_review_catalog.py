"""Gather original ranked/chronological catalogs with per-unit cache checkpoints."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.domain.artist_review_selection import earliest_releases
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate


@dataclass(frozen=True)
class ReleasePage:
    """Retain parsed candidates alongside original raw pagination authority.

    Args:
        releases: Complete associated candidates in raw rank order.
        rows: Original raw row count, including discarded records.
        has_next: Original next-page truthiness.
    """

    releases: tuple[ReleaseCandidate, ...]
    rows: int
    has_next: bool


@dataclass(frozen=True)
class RawReleasePage:
    """Carry original durable raw scan rows to the storage adapter.

    Args:
        rows: Original complete JSON rows, retained before delayed qualification.
        has_next: Original next-page truthiness.
    """

    rows: tuple[object, ...]
    has_next: bool


@dataclass(frozen=True)
class FirstTrack:
    """Retain original tolerant first-track fields without stronger qualification.

    Args:
        identity: Original first marker id or None.
        name: Original first marker name or None.
        uri: Original first marker URI or None.
        primary_id: Original first credit id or None.
        primary_name: Original first credit display name.
    """

    identity: str | None
    name: str | None
    uri: str | None
    primary_id: str | None
    primary_name: str


class CatalogScan(Protocol):
    """Expose original durable raw scan progress without importing file storage."""

    def complete(self) -> bool:
        """Read original completion truthiness.

        Returns:
            Whether the original scan is complete.
        """
        ...

    def offset(self) -> int:
        """Convert the original stored raw offset at its original read boundary.

        Returns:
            Original effective raw offset.

        Raises:
            ValueError: Original offset cannot be converted to an integer.
            TypeError: Original offset has no accepted integer representation.
        """
        ...

    def accept(self, page: RawReleasePage, offset: int) -> None:
        """Retain original raw rows, update scan progress and checkpoint in order.

        Args:
            page: Original complete raw page.
            offset: Original request offset.
        """
        ...

    def candidates(self) -> list[ReleaseCandidate]:
        """Qualify original stored raw rows only after the scan is complete.

        Returns:
            Complete associated releases in original raw rank order.
        """
        ...


class CatalogCache(Protocol):
    """Read and checkpoint original catalog units, retaining empty cache hits."""

    def tracks(self) -> list[TrackCandidate] | None:
        """Read original ranked-track cache.

        Returns:
            Original complete cached candidates or None for a miss.
        """
        ...

    def releases(self, key: str) -> list[ReleaseCandidate] | None:
        """Read one original enriched release cache.

        Args:
            key: Original catalog namespace.

        Returns:
            Original complete cached releases or None for a miss.
        """
        ...

    def save_tracks(self, tracks: list[TrackCandidate]) -> None:
        """Checkpoint original complete ranked-track metadata.

        Args:
            tracks: Original complete qualified tracks.
        """
        ...

    def save_releases(self, key: str, releases: list[ReleaseCandidate]) -> None:
        """Checkpoint original complete release metadata.

        Args:
            key: Original catalog namespace.
            releases: Original complete mutable candidates.
        """
        ...

    def scan(self) -> CatalogScan:
        """Resolve the original shared durable discography scan.

        Returns:
            Original resumable raw scan.
        """
        ...


@dataclass(frozen=True)
class ArtistCatalog:
    """Coordinate original reads, qualification and metadata checkpoint ordering.

    Args:
        cache: Original per-artist durable catalog metadata.
        tracks: Original one-page complete ranked-track reader.
        search: Original ranked release-page reader.
        discography: Original complete raw release-page reader.
        first: Original tolerant first-track reader with original 404 handling.
    """

    cache: CatalogCache
    tracks: Callable[[], list[TrackCandidate]]
    search: Callable[[int], ReleasePage]
    discography: Callable[[int], RawReleasePage]
    first: Callable[[ReleaseCandidate], FirstTrack | None]

    def ranked_tracks(self) -> list[TrackCandidate]:
        """Retain authoritative empty hits and checkpoint the first ten candidates.

        Returns:
            Original complete ordered associated tracks.
        """
        cached = self.cache.tracks()
        if cached is not None:
            return cached
        tracks = self.tracks()[:10]
        self.cache.save_tracks(tracks)
        return tracks

    def ranked_releases(self) -> list[ReleaseCandidate]:
        """Read original ranked album/EP candidates, then enrich each first track.

        Returns:
            Original enriched complete search-ranked releases.
        """
        releases = self.cache.releases("ranked_releases")
        if releases is None:
            releases = self.search_releases()
            self.cache.save_releases("ranked_releases", releases)
        return self.enrich(releases, "ranked_releases")

    def search_releases(self) -> list[ReleaseCandidate]:
        """Read at most three raw pages and stop at the tenth usable distinct release.

        Returns:
            Original associated album/EP candidates in search order.
        """
        return search_releases(self.search)

    def earliest_releases(self) -> list[ReleaseCandidate]:
        """Complete the original raw scan before chronological qualification.

        Returns:
            Original first ten chronological releases with enriched first tracks.
        """
        cached = self.cache.releases("earliest_releases")
        if cached is not None:
            return self.enrich(cached, "earliest_releases")
        scan = self.cache.scan()
        while not scan.complete():
            offset = scan.offset()
            scan.accept(self.discography(offset), offset)
        releases = earliest_releases(scan.candidates())
        self.cache.save_releases("earliest_releases", releases)
        return self.enrich(releases, "earliest_releases")

    def enrich(
        self, releases: list[ReleaseCandidate], key: str
    ) -> list[ReleaseCandidate]:
        """Checkpoint every newly checked first track, including empty/404 results.

        Args:
            releases: Original mutable catalog candidates.
            key: Original ranked or chronological metadata namespace.

        Returns:
            Original same complete mutable candidate list.
        """
        for release in releases:
            if release.first_track_checked:
                continue
            first = self.first(release)
            release.first_track_checked = True
            if first is not None:
                _assign_first(release, first)
            self.cache.save_releases(key, releases)
        return releases


def _retain_ranked(
    releases: list[ReleaseCandidate],
    seen: set[str],
    candidates: tuple[ReleaseCandidate, ...],
) -> None:
    for candidate in candidates:
        if (
            candidate.release_type not in {"Album", "EP"}
            or candidate.spotify_id in seen
        ):
            continue
        seen.add(candidate.spotify_id)
        releases.append(candidate)
        if len(releases) == 10:
            return


def _assign_first(release: ReleaseCandidate, first: FirstTrack) -> None:
    release.first_track_id = first.identity
    release.first_track_name = first.name
    release.first_track_uri = first.uri
    release.first_track_primary_artist_id = first.primary_id
    release.first_track_primary_artist_name = first.primary_name


def search_releases(read: Callable[[int], ReleasePage]) -> list[ReleaseCandidate]:
    """Read at most three raw pages and retain ten distinct ranked album/EP releases.

    Args:
        read: Original retried complete parsed search-page reader.

    Returns:
        Original complete qualifying release list in raw search order.
    """
    releases: list[ReleaseCandidate] = []
    seen: set[str] = set()
    for page_index in range(3):
        page = read(page_index * 10)
        _retain_ranked(releases, seen, page.releases)
        if len(releases) == 10:
            return releases
        if not page.has_next or not page.rows:
            break
    return releases
