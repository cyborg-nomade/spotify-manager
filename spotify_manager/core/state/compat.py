"""Compatibility boundary for migrating legacy per-routine state files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol

from spotify_manager.application.ports.state import RoutineState as RoutineState
from spotify_manager.core.state.definitions import StateDefinition
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.core.state.service import StateService


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
