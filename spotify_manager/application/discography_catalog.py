"""Gather raw-row page authority and saved membership before canonical selection."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Protocol

from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.domain.discography_catalog import canonical_releases
from spotify_manager.domain.discography_values import CatalogRelease


@dataclass(frozen=True)
class DiscographyPage:
    """Retain playable facts alongside original raw pagination accounting.

    Args:
        releases: Original usable releases in raw order.
        rows: Original raw row count, including skipped rows.
        has_next: Original truthiness of next-page authority.
    """

    releases: tuple[CatalogRelease, ...]
    rows: int
    has_next: bool


class DiscographyCatalogSource(Protocol):
    """Read raw-row catalog pages and checked saved membership."""

    def page(self, artist: str, offset: int) -> DiscographyPage:
        """Read a catalog page at its original raw offset.

        Args:
            artist: Original primary artist identity.
            offset: Original raw-row cursor.

        Returns:
            Parsed releases and complete raw pagination facts.
        """

    def saved(self, identities: list[str]) -> list[bool]:
        """Read checked saved statuses in original input order.

        Args:
            identities: Original ordered release identities.

        Returns:
            Corresponding validated membership statuses.
        """


@dataclass(frozen=True)
class DiscographyCatalog:
    """Bind original parsed pages and tolerant saved-status batches.

    Args:
        source: Parsed pages and checked membership integration.
        batch_size: Original saved-membership batch size.
    """

    source: DiscographyCatalogSource
    batch_size: int = 20

    def run(self, artist: str) -> tuple[CatalogRelease, ...]:
        """Read every page, then saved batches, then select canonical editions.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original complete canonical chronological catalog.

        Raises:
            DiscographyError: Original next-page authority has no raw rows.
        """
        releases = self._releases(artist)
        observed = []
        for start in range(0, len(releases), self.batch_size):
            batch = releases[start : start + self.batch_size]
            identities = [release.spotify_id for release in batch]
            statuses = self.source.saved(identities)
            observed.extend(_saved_releases(batch, statuses))
        return canonical_releases(observed)

    def _releases(self, artist: str) -> list[CatalogRelease]:
        candidates: dict[str, CatalogRelease] = {}
        offset = 0
        while True:
            page = self.source.page(artist, offset)
            for release in page.releases:
                candidates[release.spotify_id] = release
            offset += page.rows
            if not page.has_next:
                return list(candidates.values())
            if not page.rows:
                raise DiscographyError("Spotify returned an empty artist release page.")


def _saved_releases(
    releases: list[CatalogRelease], statuses: list[bool]
) -> list[CatalogRelease]:
    observed = []
    for release, saved in zip(releases, statuses, strict=True):
        observed.append(replace(release, saved=saved))
    return observed
