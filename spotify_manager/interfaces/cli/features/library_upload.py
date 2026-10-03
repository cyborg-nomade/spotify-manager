"""Explicit library upload CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from rich.console import Console
from rich.table import Table

from spotify_manager.application.upload_values import UploadResource
from spotify_manager.interfaces.operations import upload_library_files as hf_upload


@dataclass(kw_only=True)
class LibraryUploadCLI:
    """Execute and present library upload through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        create_table: Factory for table instances.
        format_file_size: Original format file size boundary supplied by the facade.
    """

    create_console: type[Console]
    create_table: type[Table]
    format_file_size: Callable[..., str]

    def _run_upload_library_files_to_hf(
        self,
        your_library_only: bool,
        lastfm_only: bool,
        repo_id: str,
        revision: str,
        dry_run: bool,
    ) -> None:
        """Upload refreshed Spotify and Last.fm exports to the HF Space.

        Args:
            your_library_only: Your library only supplied by the caller.
            lastfm_only: Lastfm only supplied by the caller.
            repo_id: Repo id supplied by the caller.
            revision: Revision supplied by the caller.
            dry_run: Whether to preview changes using the original routine behavior.
        """
        if your_library_only and lastfm_only:
            raise typer.BadParameter(
                "use either --your-library-only or --lastfm-only, not both"
            )
        console = self.create_console()
        try:
            with console.status("Validating library exports"):
                plan = hf_upload.prepare_library_files_upload(
                    include_your_library=not lastfm_only,
                    include_lastfm=not your_library_only,
                    repo_id=repo_id,
                    revision=revision,
                )
        except hf_upload.LibraryFilesUploadError as exc:
            self._report_upload_library_files_to_hf_library_files_upload_failure(
                exc, console
            )
        self._show_upload_plan(console, plan)
        if dry_run:
            console.print(
                (
                    "Dry run complete: "
                    f"{plan.upload_file_count}"
                    " files validated; nothing was changed."
                ),
                style="bold green",
            )
            return
        try:
            with console.status("Uploading library exports to Hugging Face"):
                result = hf_upload.upload_library_files(plan)
        except hf_upload.LibraryFilesUploadError as exc:
            self._report_upload_library_files_to_hf_library_files_upload_failure(
                exc, console
            )
        self._show_upload_library_files_to_hf(console, result)

    def _report_upload_library_files_to_hf_library_files_upload_failure(
        self, exc: hf_upload.LibraryFilesUploadError, console: Console
    ) -> Never:
        console.print(str(exc), style="bold red", markup=False)
        raise typer.Exit(code=1) from exc

    def _show_upload_library_files_to_hf(
        self, console: Console, result: hf_upload.LibraryFilesUploadResult
    ) -> None:
        console.print(
            (
                "Uploaded "
                f"{result.uploaded_files}"
                " files ("
                f"{self.format_file_size(result.upload_size_bytes)}"
                ")."
            ),
            style="bold green",
        )
        if result.deleted_stale_parts:
            console.print(
                (f"Removed {result.deleted_stale_parts} obsolete fallback parts."),
                style="yellow",
            )
        console.print(f"HF commit: {result.commit_url}", markup=False)
        console.print("The Space rebuild has been triggered.", style="dim")

    def _row_upload_library_files_to_hf_command_resource(
        self, resource: UploadResource, table: Table
    ) -> None:
        table.add_row(
            resource.name,
            (f"{resource.item_count:,}"),
            self.format_file_size(resource.size_bytes),
            resource.path_in_repo,
        )

    def _show_upload_plan(
        self, console: Console, plan: hf_upload.LibraryFilesUploadPlan
    ) -> None:
        """Show upload plan.

        Args:
            console: Rich console receiving this command's output.
            plan: Plan supplied by the caller.
        """
        table = self.create_table(title=f"HF upload: {plan.repo_id}@{plan.revision}")
        table.add_column("Export")
        table.add_column("Items", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("HF path")
        for resource in plan.resources:
            self._row_upload_library_files_to_hf_command_resource(resource, table)
        if plan.lastfm_parts:
            table.add_row(
                (f"{len(plan.lastfm_parts)} inline Last.fm fallback parts"),
                "",
                self.format_file_size(
                    sum(len(part.content) for part in plan.lastfm_parts)
                ),
                (f"{hf_upload.REMOTE_FILES_DIR}/{hf_upload.LASTFM_PART_PREFIX}*"),
                style="dim",
            )
        console.print(table)
