"""Keep collection and execution independent of operator data and services."""

import inspect
import os
import socket
import sys
from dataclasses import fields
from dataclasses import is_dataclass
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "spotify_manager" / "files"
NETWORK_EVENTS = {
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.sendto",
}
FILE_EVENTS = {"open", "os.remove", "os.rename", "os.mkdir", "os.rmdir"}
ENV_PREFIXES = (
    "SPOTIFY_MANAGER_",
    "SPOTIPY_",
    "HF_",
    "HUGGING_FACE_",
    "AUTOMATION_TOKEN",
)


def forbid_network(*args: object, **kwargs: object) -> None:
    """Reject an unexpected network request.

    Args:
        *args: Positional arguments from the patched socket operation.
        **kwargs: Keyword arguments from the patched socket operation.

    Raises:
        AssertionError: Always; tests must supply a fake transport.
    """
    raise AssertionError(
        "Unexpected network access: provide an explicit fake transport"
    )


def _synthetic_environment(temporary: Path) -> dict[str, str]:
    return {
        "SPOTIPY_CLIENT_ID": "test-client",
        "SPOTIPY_CLIENT_SECRET": "test-secret",
        "SPOTIPY_REDIRECT_URI": "http://127.0.0.1:8080/callback",
        "ALBUMS_TO_ADD": "10",
        "LIMIT": "50",
        "LASTFM_API_KEY": "test-lastfm-key",
        "LASTFM_USERNAME": "test-listener",
        "SPOTIFY_MANAGER_STATE_BACKEND": "local",
        "SPOTIFY_MANAGER_STATE_LOCAL_PATH": str(temporary / "state.json"),
        "SPOTIFY_MANAGER_DATA_BACKEND": "local",
        "SPOTIFY_MANAGER_DATA_LOCAL_ROOT": str(temporary / "data"),
        "HF_HOME": str(temporary / "hf"),
    }


def isolate_environment(patch: pytest.MonkeyPatch, temporary: Path) -> None:
    """Install synthetic configuration before collecting application imports.

    Args:
        patch: Session patch manager, restored during cleanup.
        temporary: Directory containing disposable state and caches.
    """
    from spotify_manager.settings import Settings

    for key in os.environ:
        if key.lower() in Settings.model_fields or key.startswith(ENV_PREFIXES):
            patch.delenv(key)
    for key, value in _synthetic_environment(temporary).items():
        patch.setenv(key, value)
    patch.setitem(Settings.model_config, "env_file", None)
    patch.setattr(socket.socket, "connect", forbid_network)
    patch.setattr(socket.socket, "connect_ex", forbid_network)
    patch.setattr(socket.socket, "sendto", forbid_network)
    patch.setattr(socket, "getaddrinfo", forbid_network)


def application_modules() -> list[ModuleType]:
    """Find loaded application modules whose globals need isolation.

    Returns:
        Application modules in import order, excluding incomplete imports.
    """
    result = []
    for name, module in tuple(sys.modules.items()):
        if name.startswith("spotify_manager") and isinstance(module, ModuleType):
            result.append(module)
    return result


def _relocate_mapping(value: dict[object, object], destination: Path) -> object:
    """Relocate nested paths while retaining unchanged mapping identities.

    Args:
        value: Mapping that may contain paths in keys or values.
        destination: Directory replacing the operator's artifact root.

    Returns:
        A relocated copy if any key or value changed, otherwise the original.
    """
    result = {}
    changed = False
    for key, item in value.items():
        new_key = _relocated(key, destination)
        new_item = _relocated(item, destination)
        result[new_key] = new_item
        changed |= new_key is not key or new_item is not item
    return result if changed else value


def _relocate_sequence(
    value: tuple[object, ...] | list[object], destination: Path
) -> object:
    """Relocate sequence paths without replacing unchanged fixture objects.

    Args:
        value: Tuple or list that may contain paths or nested containers.
        destination: Directory replacing the operator's artifact root.

    Returns:
        The original sequence or a relocated copy with the same container type.
    """
    result = []
    changed = False
    for item in value:
        replacement = _relocated(item, destination)
        result.append(replacement)
        changed |= replacement is not item
    if not changed:
        return value
    return tuple(result) if isinstance(value, tuple) else result


def _relocate_dataclass(value: object, destination: Path) -> object:
    """Relocate constructor fields without changing unrelated dataclass state.

    Args:
        value: Object to inspect; non-dataclass values are returned unchanged.
        destination: Directory replacing the operator's artifact root.

    Returns:
        The original object or a dataclass copy with relocated fields.
    """
    if not is_dataclass(value) or isinstance(value, type):
        return value
    changes = {}
    for field in fields(value):
        if not field.init:
            continue
        original = getattr(value, field.name)
        replacement = _relocated(original, destination)
        if replacement is not original:
            changes[field.name] = replacement
    return replace(value, **changes) if changes else value


def _relocated(value: object, destination: Path) -> object:
    if isinstance(value, Path) and value.is_relative_to(FILES):
        return destination / value.relative_to(FILES)
    if isinstance(value, dict):
        return _relocate_mapping(value, destination)
    if isinstance(value, (tuple, list)):
        return _relocate_sequence(value, destination)
    return _relocate_dataclass(value, destination)


def _redirect_defaults(
    patch: pytest.MonkeyPatch,
    value: object,
    destination: Path,
    seen: set[int],
) -> None:
    """Patch previously bound function defaults once per function identity.

    Args:
        patch: Per-test patch manager.
        value: Module attribute that may be a function.
        destination: Directory replacing the operator's artifact root.
        seen: Function identities already handled through another import alias.
    """
    if not inspect.isfunction(value) or id(value) in seen:
        return
    seen.add(id(value))
    if value.__defaults__:
        patch.setattr(
            value, "__defaults__", _relocated(value.__defaults__, destination)
        )
    if value.__kwdefaults__:
        patch.setattr(
            value, "__kwdefaults__", _relocated(value.__kwdefaults__, destination)
        )


def _redirect_module(
    patch: pytest.MonkeyPatch,
    module: ModuleType,
    destination: Path,
    seen: set[int],
) -> None:
    """Redirect module globals and defaults, preserving imported aliases.

    Args:
        patch: Per-test patch manager.
        module: Loaded application module to inspect.
        destination: Directory replacing the operator's artifact root.
        seen: Function identities already handled in any module.
    """
    for name, value in tuple(vars(module).items()):
        if name.startswith("__"):
            continue
        replacement = _relocated(value, destination)
        if replacement is not value:
            patch.setattr(module, name, replacement)
        _redirect_defaults(patch, value, destination, seen)


def redirect_artifacts(patch: pytest.MonkeyPatch, temporary: Path) -> None:
    """Redirect imported paths, bound defaults, and relative files per test.

    Args:
        patch: Per-test patch manager.
        temporary: Empty directory for this test's artifacts.

    Raises:
        OSError: The artifact directory cannot be created or entered.
    """
    destination = temporary / "files"
    destination.mkdir()
    seen: set[int] = set()
    for module in application_modules():
        _redirect_module(patch, module, destination, seen)
    patch.chdir(temporary)


def _protect_path(argument: object) -> None:
    if not isinstance(argument, (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(argument)).resolve()
    protected = (
        path.is_relative_to(FILES)
        or path == ROOT / ".env"
        or path.is_relative_to(ROOT / "spotify_manager" / "auth")
    )
    if protected:
        raise AssertionError(f"Operator file access forbidden in tests: {path.name}")


def protect_operator_files(event: str, args: tuple[object, ...]) -> None:
    """Reject network operations and missed artifact paths, including reads.

    Args:
        event: Python audit event name.
        args: Event arguments, including source and destination for renames.

    Raises:
        AssertionError: An operation would access operator files or the network.
    """
    if event in NETWORK_EVENTS:
        forbid_network()
    if event not in FILE_EVENTS:
        return
    paths = args[:2] if event == "os.rename" else args[:1]
    for argument in paths:
        _protect_path(argument)
