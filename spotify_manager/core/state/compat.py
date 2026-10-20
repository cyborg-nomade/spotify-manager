"""Compatibility boundary for migrating legacy per-routine state files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol

from spotify_manager.application.ports.state import RoutineState as RoutineState
from spotify_manager.core.state.definitions import StateDefinition
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateService
from spotify_manager.core.state.service import StateValidator


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


class RoutineStateCodec(StateDefinition, Protocol):
    """Read and validate the retained file format as well as its shared namespace."""

    def load(self, path: Path) -> dict[str, Any]:
        """Read an explicit legacy file.

        Args:
            path: Caller-selected legacy path.

        Returns:
            Complete validated state.
        """
        ...

    def save(self, value: dict[str, Any], path: Path) -> None:
        """Accept an explicit legacy file.

        Args:
            value: Complete current state.
            path: Caller-selected legacy path.
        """
        ...


@dataclass(frozen=True)
class StateLocation:
    """Describe path compatibility and an optional supplied state authority.

    Args:
        path: Requested legacy path.
        default_path: Conventional path redirected to shared state.
        service: Optional caller-owned shared service.
    """

    path: Path
    default_path: Path
    service: StateService | None = None


@dataclass(frozen=True)
class CodecFileState:
    """Own explicit legacy file access without load/save callbacks.

    Args:
        codec: Named routine format.
        path: Explicit legacy file.
    """

    codec: RoutineStateCodec
    path: Path

    def load(self) -> dict[str, Any]:
        """Read the legacy file.

        Returns:
            Original normalized state.
        """
        return self.codec.load(self.path)

    def save(self, value: dict[str, Any], *, message: str | None = None) -> None:
        """Accept the legacy file through its original writer.

        Args:
            value: Complete current state.
            message: Shared-service provenance, unused by legacy files.
        """
        self.codec.save(value, self.path)


def routine_state_from(
    name: str, codec: RoutineStateCodec, location: StateLocation
) -> RoutineState:
    """Resolve shared state or an explicit legacy path using a named format.

    Args:
        name: Routine namespace identity.
        codec: Default, validation and file-format owner.
        location: Requested path and optional supplied authority.

    Returns:
        Original selected state authority with unchanged conflict semantics.
    """
    if location.service is not None:
        return location.service.namespace(name, codec)
    if location.path != location.default_path:
        return CodecFileState(codec, location.path)
    return get_state_service().namespace(name, codec)
