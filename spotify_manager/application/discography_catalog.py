"""Gather raw-row page authority and saved membership before canonical selection."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace

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


@dataclass(frozen=True)
class DiscographyCatalog:
    """Bind original parsed pages and tolerant saved-status batches.

    Args:
        page: Original page reader with caller retry and raw parsing.
        saved: Original checked saved-status batch reader.
        batch_size: Original saved-membership batch size.
    """

    page: Callable[[int], DiscographyPage]
    saved: Callable[[list[str]], list[bool]]
    batch_size: int = 20

    def run(self) -> tuple[CatalogRelease, ...]:
        """Read every page, then saved batches, then select canonical editions.

        Returns:
            Original complete canonical chronological catalog.

        Raises:
            DiscographyError: Original next-page authority has no raw rows.
        """
        releases = self._releases()
        observed = []
        for start in range(0, len(releases), self.batch_size):
            batch = releases[start : start + self.batch_size]
            identities = [release.spotify_id for release in batch]
            statuses = self.saved(identities)
            observed.extend(_saved_releases(batch, statuses))
        return canonical_releases(observed)

    def _releases(self) -> list[CatalogRelease]:
        candidates: dict[str, CatalogRelease] = {}
        offset = 0
        while True:
            page = self.page(offset)
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
