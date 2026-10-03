"""Explicit state CLI execution, prompts and presentation."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Never

import typer
from rich.console import Console

from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.service import StateService


@dataclass(kw_only=True)
class StateCLI:
    """Execute and present state through explicit facade dependencies.

    Args:
        create_console: Factory for console instances.
        get_state_service: Original get state service boundary supplied by the facade.
    """

    create_console: type[Console]
    get_state_service: Callable[..., StateService]

    def _run_state_show(self, namespace: str | None) -> None:
        """Print the current shared state and its guarded revision.

        Args:
            namespace: Namespace supplied by the caller.
        """
        try:
            snapshot = self.get_state_service().snapshot()
            payload = self._select_state_payload(snapshot.document, namespace)
            self.create_console().print_json(
                json.dumps(
                    {"revision": snapshot.revision, "state": payload},
                    ensure_ascii=False,
                )
            )
        except StateError as exc:
            self._report_state_show_state_failure(exc)

    def _run_state_export(
        self,
        destination: Annotated[Path, typer.Argument(help="Destination JSON file.")],
    ) -> None:
        """Export a readable snapshot of the complete shared state.

        Args:
            destination: Destination supplied by the caller.
        """
        try:
            snapshot = self.get_state_service().export(destination)
        except (OSError, StateError) as exc:
            self._report_state_export_o_s_failure(exc)
        typer.echo(f"Exported revision {snapshot.revision} to {destination.resolve()}.")

    def _run_state_edit(
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
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise StateDocumentError("Edited state must be a JSON object.")
            document = raw.get("document", raw)
            source_revision = raw.get("revision") if "document" in raw else None
            if not isinstance(document, dict):
                raise StateDocumentError("Edited state document must be a JSON object.")
            service = self.get_state_service()
            current = service.snapshot()
            source_updated_at = document.get("updated_at")
            current_updated_at = current.document.get("updated_at")
            stale = (
                source_revision != current.revision
                if isinstance(source_revision, str)
                else source_updated_at != current_updated_at
            )
            if not force and stale:
                raise StateDocumentError(
                    "Edited snapshot is stale. Export the current state or use --force."
                )
            if not yes and (
                not typer.confirm(f"Replace shared state revision {current.revision}?")
            ):
                typer.echo("State was not changed.")
                return
            saved = service.replace(
                document,
                expected_revision=current.revision,
                message=(f"Edit Spotify Manager state from {source.name}"),
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
