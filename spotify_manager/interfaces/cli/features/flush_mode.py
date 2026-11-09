"""Inspect global policy and admit CLI commands before hydration or effects."""

import json
from dataclasses import asdict
from typing import cast

import typer

from spotify_manager.application.flush_mode import FlushModeBlockedError
from spotify_manager.application.flush_mode import FlushModeStore
from spotify_manager.application.flush_mode import NewWineMode
from spotify_manager.application.flush_mode import check_flush_mode
from spotify_manager.application.flush_mode import new_wine_no_discovery
from spotify_manager.application.flush_mode import require_routine_start
from spotify_manager.bootstrap import flush_mode as composition
from spotify_manager.core.state.models import StateError
from spotify_manager.domain.flush_mode import BLOCKED_COMMANDS
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import flush_reason
from spotify_manager.interfaces.cli.resources import CliResources


def require_start(command: str | None) -> None:
    """Reject restricted CLI starts before hydration or client construction.

    Args:
        command: Typer's selected command, including resumed routine invocations.

    Raises:
        typer.Exit: The policy blocks admission or cannot be read safely.
    """
    canonical = (command or "").replace("-", "_")
    if canonical not in BLOCKED_COMMANDS:
        return
    try:
        require_routine_start(canonical, composition.flush_mode_state().load())
    except (FlushModeBlockedError, StateError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


async def wine_mode(requested: bool) -> NewWineMode:
    """Resolve New Wine policy once at the CLI invocation boundary.

    Args:
        requested: Ordinary operator setting.

    Returns:
        Effective initial No Discovery setting.

    Raises:
        typer.Exit: Shared control cannot be read safely.
    """
    try:
        state = await composition.async_flush_mode_state().load()
    except StateError as exc:
        typer.echo("Flush Mode state is unavailable; start blocked.", err=True)
        raise typer.Exit(1) from exc
    return new_wine_no_discovery(requested, state)


async def run_flush_mode(
    check: bool, control: str | None, runtime: CliResources
) -> None:
    """Inspect policy, persist an override and optionally refresh live counts.

    Args:
        check: Whether to read both live counts and update automatic observations.
        control: Optional automatic, on or off selection.
        runtime: Invocation-owned client resources, unused for status/control only.

    Raises:
        typer.Exit: Control is invalid or state cannot be read/written.
    """
    if control is not None and control not in {"automatic", "on", "off"}:
        typer.echo("Control must be automatic, on or off.", err=True)
        raise typer.Exit(2)
    store = composition.async_flush_mode_state()
    try:
        if control is not None:
            await store.control(cast(FlushControl, control))
        state = await _checked_state(check, runtime, store)
    except StateError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        json.dumps(
            {**asdict(state), "active": state.active, "reason": flush_reason(state)},
            indent=2,
        )
    )


async def _checked_state(
    check: bool, runtime: CliResources, store: FlushModeStore
) -> FlushState:
    if not check:
        return await store.load()
    return await check_flush_mode(
        store,
        composition.queue_counts(await runtime.client()),
        composition.FlushModeClock(),
    )
