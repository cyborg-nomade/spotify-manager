"""Run annual discovery imports as an explicit application stage."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.application.queue_3_import_review import ImportReviewPresentation
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist


@dataclass(frozen=True)
class AnnualDiscoveryInputs:
    """Hold the independently observed annual import inputs.

    Args:
        playlist: Queue 3 destination identity.
        current: Original complete current markers.
        state: Original loaded or preview-cloned authority.
        owned: Original complete owned playlist facts.
        importer: Configured named import stage.
    """

    playlist: str
    current: list[PlaylistTrack]
    state: dict[str, object]
    owned: tuple[OwnedPlaylist, ...]
    importer: AnnualDiscoveryImport


class AnnualDiscoverySource(Protocol):
    """Observe annual import authority without executing the import."""

    async def discovery_inputs(self, preview: bool) -> AnnualDiscoveryInputs:
        """Read the original annual import sources.

        Args:
            preview: Whether mutable progress is cloned.

        Returns:
            Original ordered observations and invocation-owned import resources.
        """


class DiscoveryPresentation(ImportReviewPresentation, Protocol):
    """Present the independently requested annual import's boundaries."""

    def loading(self, year: int) -> None:
        """Present the original annual source year.

        Args:
            year: Previous-year source identity.
        """


@dataclass(frozen=True)
class AnnualDiscoveries:
    """Own the visible path from retrospective execution to annual import rules.

    Args:
        source: Original import observations.
        presentation: Original import progress and completion presenter.
    """

    source: AnnualDiscoverySource
    presentation: DiscoveryPresentation

    async def run(self, active_year: int, preview: bool) -> None:
        """Run the original import without changing its standalone summary behavior.

        Args:
            active_year: Original source year plus one.
            preview: Original mutation and checkpoint suppression.
        """
        self.presentation.loading(active_year - 1)
        inputs = await self.source.discovery_inputs(preview)
        await AnnualImportReview(inputs.importer, self.presentation).run(
            inputs.playlist,
            inputs.current,
            inputs.state,
            inputs.owned,
            active_year,
            preview,
        )
