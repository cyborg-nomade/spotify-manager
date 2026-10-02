"""Adapt original mutable catalog JSON and raw scan checkpoint semantics."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import cast

from spotify_manager.application.artist_review_catalog import CatalogScan
from spotify_manager.application.artist_review_catalog import RawReleasePage
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate
from spotify_manager.infrastructure import artist_review_records as records


@dataclass(frozen=True)
class LegacyScan:
    """Retain original mutable raw scan, late shape validation and persistence.

    Args:
        artist: Original expected associated identity.
        name: Original reviewed display name.
        raw: Original same mutable durable scan object.
        persist: Original whole-cache checkpoint.
    """

    artist: str
    name: str
    raw: dict[str, object]
    persist: Callable[[], None]

    def complete(self) -> bool:
        """Read original completion truthiness without strengthening validation.

        Returns:
            Original complete flag truthiness.
        """
        return bool(self.raw.get("complete"))

    def offset(self) -> int:
        """Retain original conversion of the durable raw offset.

        Returns:
            Original effective offset.

        Raises:
            ValueError: Original offset cannot form an integer.
            TypeError: Original offset has no integer representation.
        """
        return int(cast(int | float | str, self.raw.get("offset", 0)))

    def accept(self, page: RawReleasePage, offset: int) -> None:
        """Update original in-memory progress before guarding and checkpointing.

        Args:
            page: Original complete raw page.
            offset: Original request offset.

        Raises:
            ArtistReviewError: Cached rows are invalid or next authority is empty.
        """
        items = self.raw.setdefault("items", [])
        if not isinstance(items, list):
            raise ArtistReviewError(f"Invalid cached discography for {self.name}.")
        items.extend(page.rows)
        self.raw["offset"] = offset + len(page.rows)
        self.raw["complete"] = not page.has_next
        if not page.rows and page.has_next:
            raise ArtistReviewError(
                f"Spotify returned an empty release page for {self.name}."
            )
        self.persist()

    def candidates(self) -> list[ReleaseCandidate]:
        """Decode original complete raw scan only after pagination ends.

        Returns:
            Original complete associated candidates.

        Raises:
            AssertionError: Original stored complete rows are not a list.
        """
        return records.scanned_releases(self.raw.get("items", []), self.artist)


@dataclass
class LegacyCatalogCache:
    """Retain original shared mutable metadata and per-unit publication boundaries.

    Args:
        artist: Original current reviewed identity.
        name: Original reviewed display name.
        cache: Original same mutable complete metadata dictionary.
        persist: Original whole-cache checkpoint.
        data: Original same artist-specific mutable record.
    """

    artist: str
    name: str
    cache: dict[str, dict[str, object]]
    persist: Callable[[], None]
    data: dict[str, object] = field(init=False)

    def __post_init__(self) -> None:
        """Resolve original same artist-specific metadata without eager validation."""
        self.data = self.cache.setdefault(self.artist, {})

    def tracks(self) -> list[TrackCandidate] | None:
        """Read the original permissive ranked-track constructor boundary.

        Returns:
            Original complete cached list or None for a miss.
        """
        return records.cached_tracks(self.data.get("ranked_tracks"))

    def releases(self, key: str) -> list[ReleaseCandidate] | None:
        """Read one original permissive release constructor boundary.

        Args:
            key: Original release metadata namespace.

        Returns:
            Original complete cached list or None for a miss.
        """
        return records.cached_releases(self.data.get(key))

    def save_tracks(self, tracks: list[TrackCandidate]) -> None:
        """Assign original complete tracks before checkpoint publication.

        Args:
            tracks: Original associated ranked facts.
        """
        self.data["ranked_tracks"] = [asdict(track) for track in tracks]
        self.persist()

    def save_releases(self, key: str, releases: list[ReleaseCandidate]) -> None:
        """Assign original complete releases before checkpoint publication.

        Args:
            key: Original metadata namespace.
            releases: Original mutable complete candidates.
        """
        self.data[key] = [asdict(release) for release in releases]
        self.persist()

    def scan(self) -> CatalogScan:
        """Resolve original mutable raw scan and its original shape guard.

        Returns:
            Original complete/resumable raw scan adapter.

        Raises:
            ArtistReviewError: The original stored scan is not an object.
        """
        raw = self.data.setdefault(
            "discography_scan", {"offset": 0, "complete": False, "items": []}
        )
        if not isinstance(raw, dict):
            raise ArtistReviewError(f"Invalid cached discography for {self.name}.")
        return LegacyScan(self.artist, self.name, raw, self.persist)
