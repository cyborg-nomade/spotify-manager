"""Complete the independently requested annual import and its public summary."""

from dataclasses import dataclass
from typing import Protocol
from typing import cast

from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.application.queue_3_values import AnnualImportSummary
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist


class ImportReviewPresentation(Protocol):
    """Present standalone import status through the original output boundaries."""

    def already_imported(self, year: int) -> None:
        """Explain an existing completion checkpoint.

        Args:
            year: Previous-year source playlist year.
        """

    def checked(self, year: int, already_completed: bool) -> None:
        """Report final progress after the summary decision.

        Args:
            year: Previous-year source playlist year.
            already_completed: Whether the stored checkpoint suppressed import.
        """


@dataclass(frozen=True)
class AnnualImportReview:
    """Wrap annual import decisions in the standalone command's summary contract.

    Args:
        importer: Annual source selection and accepted-effect workflow.
        presentation: Existing completion message and final progress callbacks.
    """

    importer: AnnualDiscoveryImport
    presentation: ImportReviewPresentation

    def run(
        self,
        playlist_id: str,
        current: list[PlaylistTrack],
        state: dict[str, object],
        owned: tuple[OwnedPlaylist, ...],
        year: int,
        dry_run: bool,
    ) -> AnnualImportSummary:
        """Honor saved completion and summarize a requested annual import.

        Args:
            playlist_id: Queue 3 destination.
            current: Already observed destination markers.
            state: Working namespace, cloned by the boundary for previews.
            owned: Already observed owned playlists.
            year: Active checkpoint year.
            dry_run: Whether this is a preview.

        Returns:
            Original public import summary and ordered artist decisions.

        Raises:
            Queue3Error: Source resolution or an external import effect fails.
            KeyError: The annual import state container is missing.
        """
        imports = cast(dict[str, object], state["annual_imports"])
        previous = imports.get(str(year))
        completed = isinstance(previous, dict) and bool(previous.get("completed"))
        if completed:
            self.presentation.already_imported(year - 1)
            self.presentation.checked(year - 1, True)
            return AnnualImportSummary(year, year - 1, 0, 0, True, dry_run, ())
        _tracks, results = self.importer.run(
            playlist_id, current, state, owned, year, dry_run
        )
        additions = sum(result.action in {"added", "would add"} for result in results)
        already_present = sum(result.action == "already present" for result in results)
        self.presentation.checked(year - 1, False)
        return AnnualImportSummary(
            year, year - 1, additions, already_present, False, dry_run, results
        )
