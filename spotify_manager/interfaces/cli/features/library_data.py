"""Explicit library data CLI execution, prompts and presentation."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated
from typing import Never

import typer
from rich.console import Console
from rich.table import Table

from spotify_manager.core.library_data import ALL_ARTIFACTS
from spotify_manager.core.library_data import ArtifactName
from spotify_manager.core.library_data import LibraryDataError
from spotify_manager.core.library_data.models import validate_artifact_name
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.interfaces.cli.formatting import format_file_size
from spotify_manager.interfaces.cli.resources import CliResources


@dataclass(kw_only=True)
class LibraryDataCLI:
    """Inspect, hydrate and publish durable library artifacts.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        create_console: Interface presentation resource.
        create_table: Interface presentation resource.
    """

    runtime: CliResources

    create_console: type[Console]
    create_table: type[Table]

    def _selected_artifacts(self, values: Iterable[str]) -> tuple[ArtifactName, ...]:
        """Validate repeated artifact options, defaulting to every artifact.

        Args:
            values: Values supplied by the caller.

        Returns:
            The original value selected or formatted by this adapter.
        """
        requested = tuple(values)
        if not requested:
            return ALL_ARTIFACTS
        try:
            return tuple(
                dict.fromkeys(validate_artifact_name(value) for value in requested)
            )
        except LibraryDataError as exc:
            self._report_selected_artifacts_library_data_failure(exc)

    def _format_file_size(self, size_bytes: int) -> str:
        """Format a byte count for a compact CLI summary.

        Args:
            size_bytes: Byte count.

        Returns:
            Original display text.
        """
        return format_file_size(size_bytes)

    def _run_library_data_status(self) -> None:
        """Show durable versions and local synchronization for canonical files."""
        console = self.create_console()
        try:
            statuses = self.runtime.get_library_data_service().statuses()
        except LibraryDataError as exc:
            self._report_library_data_status_library_data_failure(exc, console)
        table = self.create_table(title="Shared library data")
        table.add_column("Artifact")
        table.add_column("Updated")
        table.add_column("Size", justify="right")
        table.add_column("Source")
        table.add_column("Local")
        for item in statuses:
            table.add_row(
                item.filename,
                item.updated_at or ("Not published"),
                self._format_file_size(item.size_bytes)
                if item.size_bytes is not None
                else "-",
                item.source or ("-"),
                "Current" if item.local_current else "Different",
            )
        console.print(table)

    def _run_library_data_pull(
        self,
        artifact: Annotated[
            list[str] | None,
            typer.Option(
                "--artifact",
                "-a",
                help="Pull albums, tracks, artists, or scrobbles; repeat as needed.",
            ),
        ],
    ) -> None:
        """Hydrate canonical working files from the shared dataset.

        Args:
            artifact: Artifact supplied by the caller.
        """
        console = self.create_console()
        service = self.runtime.get_library_data_service()
        try:
            statuses = self._hydrate_artifacts(
                service, self._selected_artifacts(artifact or ())
            )
        except LibraryDataError as exc:
            self._report_library_data_pull_library_data_failure(exc, console)
        for item in statuses:
            state = (
                "current" if item.exists else "not published; local fallback retained"
            )
            console.print(f"{item.filename}: {state}")

    def _run_library_data_push(
        self,
        artifact: Annotated[
            list[str] | None,
            typer.Option(
                "--artifact",
                "-a",
                help="Push albums, tracks, artists, or scrobbles; repeat as needed.",
            ),
        ],
        yes: bool,
    ) -> None:
        """Publish canonical working files to the shared dataset.

        Args:
            artifact: Artifact supplied by the caller.
            yes: Yes supplied by the caller.
        """
        names = self._selected_artifacts(artifact or ())
        if not yes and (
            not typer.confirm(
                "Publish local canonical files for " + ", ".join(names) + "?"
            )
        ):
            typer.echo("Library data was not changed.")
            return
        console = self.create_console()
        service = self.runtime.get_library_data_service()
        try:
            for name in names:
                saved = service.publish(name, source="manual CLI publication")
                console.print(f"Published {name} at revision {saved.revision}.")
        except LibraryDataError as exc:
            self._report_library_data_push_library_data_failure(exc, console)

    def _report_selected_artifacts_library_data_failure(
        self, exc: LibraryDataError
    ) -> Never:
        raise typer.BadParameter(str(exc), param_hint="--artifact") from exc

    def _report_library_data_status_library_data_failure(
        self, exc: LibraryDataError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_library_data_pull_library_data_failure(
        self, exc: LibraryDataError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _report_library_data_push_library_data_failure(
        self, exc: LibraryDataError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _hydrate_artifacts(
        self, service: LibraryDataService, names: tuple[ArtifactName, ...]
    ) -> list[ArtifactStatus]:
        statuses = []
        for name in names:
            statuses.append(service.hydrate(name))
        return statuses
