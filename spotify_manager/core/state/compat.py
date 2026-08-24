"""Compatibility boundary for migrating legacy per-routine state files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from typing import Protocol

from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateService
from spotify_manager.core.state.service import StateValidator


class RoutineState(Protocol):
    """Minimal state interface consumed by routine business logic."""

    def load(self) -> dict[str, Any]:
        """Load this routine's validated state."""

    def save(
        self,
        value: dict[str, Any],
        *,
        message: str | None = None,
    ) -> object:
        """Persist this routine's complete state."""


class LegacyFileState:
    """Keep explicit test paths behind the same routine state interface."""

    def __init__(
        self,
        loader: Callable[[Path], dict[str, Any]],
        saver: Callable[[dict[str, Any], Path], None],
        path: Path,
    ) -> None:
        """Wrap legacy load/save functions for one explicit path."""
        self._loader = loader
        self._saver = saver
        self._path = path

    def load(self) -> dict[str, Any]:
        """Load through the legacy routine validator."""
        return self._loader(self._path)

    def save(
        self,
        value: dict[str, Any],
        *,
        message: str | None = None,
    ) -> None:
        """Save through the legacy atomic writer."""
        del message
        self._saver(value, self._path)


def routine_state(
    *,
    name: str,
    default_factory: Callable[[], dict[str, Any]],
    validator: StateValidator,
    legacy_path: Path,
    default_legacy_path: Path,
    legacy_loader: Callable[[Path], dict[str, Any]],
    legacy_saver: Callable[[dict[str, Any], Path], None],
    service: StateService | None = None,
) -> RoutineState:
    """Resolve production state centrally and explicit old paths compatibly."""
    if service is not None:
        return service.namespace(name, default_factory, validator)
    if legacy_path != default_legacy_path:
        return LegacyFileState(legacy_loader, legacy_saver, legacy_path)
    central = get_state_service()
    return central.namespace(name, default_factory, validator)
