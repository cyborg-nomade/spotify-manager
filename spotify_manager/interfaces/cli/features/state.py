"""Explicit state CLI execution, prompts and presentation."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Never

import typer
from rich.console import Console

from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.infrastructure.state_administration import StateAdministration
from spotify_manager.interfaces.cli.resources import CliResources
from spotify_manager.interfaces.cli.terminal import terminal_confirm


@dataclass(kw_only=True)
class StateCLI:
    """Inspect, export and edit shared routine state.

    Args:
        runtime: Lazy client, configuration and shared-service resources.
        create_console: Interface presentation resource.
    """

    runtime: CliResources

    create_console: type[Console]

    async def _run_state_show(self, namespace: str | None) -> None:
        """Print the current shared state and its guarded revision.

        Args:
            namespace: Namespace supplied by the caller.
        """
        try:
            service = StateAdministration(await self.runtime.get_state_service())
            snapshot = await service.snapshot()
            payload = self._select_state_payload(snapshot.document, namespace)
            self.create_console().print_json(
                json.dumps(
                    {"revision": snapshot.revision, "state": payload},
                    ensure_ascii=False,
                )
            )
        except StateError as exc:
            self._report_state_show_state_failure(exc)

    async def _run_state_export(
        self,
        destination: Annotated[Path, typer.Argument(help="Destination JSON file.")],
    ) -> None:
        """Export a readable snapshot of the complete shared state.

        Args:
            destination: Destination supplied by the caller.
        """
        try:
            service = StateAdministration(await self.runtime.get_state_service())
            snapshot = await service.export(destination)
        except (OSError, StateError) as exc:
            self._report_state_export_o_s_failure(exc)
        typer.echo(f"Exported revision {snapshot.revision} to {destination.resolve()}.")

    async def _run_state_edit(
        self,
        source: Annotated[
            Path, typer.Argument(help="Edited JSON state snapshot to apply.")
        ],
        force: bool,
        yes: bool,
    ) -> None:
        """Validate and apply an edited shared-state snapshot safely.

        Args:
            source: Source supplied by the caller.
            force: Force supplied by the caller.
            yes: Yes supplied by the caller.
        """
        try:
            edit = await read_state_edit(source)
            service = StateAdministration(await self.runtime.get_state_service())
            current = await service.snapshot()
            validate_edit_revision(edit, current, force)
            if not yes and (
                not await terminal_confirm(
                    f"Replace shared state revision {current.revision}?"
                )
            ):
                typer.echo("State was not changed.")
                return
            saved = await service.replace(
                edit.document,
                current.revision,
                (f"Edit Spotify Manager state from {source.name}"),
            )
        except (OSError, json.JSONDecodeError, StateError) as exc:
            self._report_state_edit_o_s_failure(exc)
        typer.echo(f"Shared state updated at revision {saved.revision}.")

    def _report_state_show_state_failure(self, exc: StateError) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _report_state_export_o_s_failure(self, exc: OSError | StateError) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _report_state_edit_o_s_failure(
        self, exc: OSError | json.JSONDecodeError | StateError
    ) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _select_state_payload(
        self, document: dict[str, Any], namespace: str | None
    ) -> object:
        if namespace is None:
            return document
        envelope = document["namespaces"].get(namespace)
        if envelope is None:
            raise StateDocumentError(f"State namespace {namespace!r} was not found.")
        return envelope


@dataclass(frozen=True)
class StateEdit:
    """Retain an edited external document and its optional export revision.

    Args:
        document: Original permissive JSON document, validated by the state service.
        revision: Original export revision, including malformed values.
    """

    document: dict[str, Any]
    revision: object


async def read_state_edit(path: Path) -> StateEdit:
    """Read the original complete external edit without blocking the CLI loop.

    Args:
        path: Original operator-selected JSON file.

    Returns:
        Original document and optional export revision.

    Raises:
        OSError: The file cannot be read.
        JSONDecodeError: The original JSON is invalid.
        StateDocumentError: The root or embedded document is not a record.
    """
    async with blocking_capacity():
        task = asyncio.create_task(asyncio.to_thread(_read_state_edit, path))
        return await finish_blocking(task)


def _read_state_edit(path: Path) -> StateEdit:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StateDocumentError("Edited state must be a JSON object.")
    document = raw.get("document", raw)
    revision = raw.get("revision") if "document" in raw else None
    if not isinstance(document, dict):
        raise StateDocumentError("Edited state document must be a JSON object.")
    return StateEdit(document, revision)


def validate_edit_revision(
    edit: StateEdit, current: StateSnapshot, force: bool
) -> None:
    """Retain the original revision or timestamp comparison before confirmation.

    Args:
        edit: Original external edit and export metadata.
        current: Current shared authority and revision.
        force: Original option bypassing the stale-export check.

    Raises:
        StateDocumentError: The original edit is stale and force is absent.
    """
    stale = (
        edit.revision != current.revision
        if isinstance(edit.revision, str)
        else edit.document.get("updated_at") != current.document.get("updated_at")
    )
    if not force and stale:
        raise StateDocumentError(
            "Edited snapshot is stale. Export the current state or use --force."
        )
