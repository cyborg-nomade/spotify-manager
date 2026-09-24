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


def forbid_network(*args: object, **kwargs: object) -> None:
    raise AssertionError(
        "Unexpected network access: provide an explicit fake transport"
    )


def isolate_environment(patch: pytest.MonkeyPatch, temporary: Path) -> None:
    """Install synthetic configuration before application modules are collected."""
    from spotify_manager.settings import Settings

    for key in os.environ:
        if key.lower() in Settings.model_fields or key.startswith(
            ("SPOTIFY_MANAGER_", "SPOTIPY_", "HF_", "HUGGING_FACE_", "AUTOMATION_TOKEN")
        ):
            patch.delenv(key)
    for key, value in {
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
    }.items():
        patch.setenv(key, value)
    patch.setitem(Settings.model_config, "env_file", None)
    patch.setattr(socket.socket, "connect", forbid_network)
    patch.setattr(socket.socket, "connect_ex", forbid_network)
    patch.setattr(socket.socket, "sendto", forbid_network)
    patch.setattr(socket, "getaddrinfo", forbid_network)


def application_modules() -> list[ModuleType]:
    return [
        module
        for name, module in tuple(sys.modules.items())
        if name.startswith("spotify_manager") and isinstance(module, ModuleType)
    ]


def redirect_artifacts(patch: pytest.MonkeyPatch, temporary: Path) -> None:
    """Redirect imported constants and already-bound Path defaults, per test."""
    destination = temporary / "files"
    destination.mkdir()

    def relocated(value: object) -> object:
        if isinstance(value, Path) and value.is_relative_to(FILES):
            return destination / value.relative_to(FILES)
        if isinstance(value, dict):
            items = [(relocated(key), relocated(item)) for key, item in value.items()]
            if any(
                k is not old_k or v is not old_v
                for (k, v), (old_k, old_v) in zip(items, value.items(), strict=True)
            ):
                return dict(items)
        if isinstance(value, (tuple, list)):
            sequence = [relocated(item) for item in value]
            if any(a is not b for a, b in zip(sequence, value, strict=True)):
                return tuple(sequence) if isinstance(value, tuple) else sequence
        if is_dataclass(value) and not isinstance(value, type):
            changes = {
                field.name: relocated(getattr(value, field.name))
                for field in fields(value)
                if field.init
            }
            if any(item is not getattr(value, name) for name, item in changes.items()):
                return replace(value, **changes)
        return value

    seen: set[int] = set()
    for module in application_modules():
        for name, value in tuple(vars(module).items()):
            if name.startswith("__"):
                continue
            replacement = relocated(value)
            if replacement is not value:
                patch.setattr(module, name, replacement)
            if inspect.isfunction(value) and id(value) not in seen:
                seen.add(id(value))
                if value.__defaults__:
                    patch.setattr(
                        value, "__defaults__", tuple(map(relocated, value.__defaults__))
                    )
                if value.__kwdefaults__:
                    patch.setattr(
                        value,
                        "__kwdefaults__",
                        {
                            key: relocated(item)
                            for key, item in value.__kwdefaults__.items()
                        },
                    )
    patch.chdir(temporary)


def protect_operator_files(event: str, args: tuple[object, ...]) -> None:
    """Reject missed artifact paths, including reads, instead of using real data."""
    if event in {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.sendto",
    }:
        forbid_network()
    if event not in {
        "open",
        "os.remove",
        "os.rename",
        "os.mkdir",
        "os.rmdir",
    }:
        return
    for argument in args[:2] if event == "os.rename" else args[:1]:
        if not isinstance(argument, (str, bytes, os.PathLike)):
            continue
        path = Path(os.fsdecode(argument)).resolve()
        if (
            path.is_relative_to(FILES)
            or path == ROOT / ".env"
            or path.is_relative_to(ROOT / "spotify_manager" / "auth")
        ):
            raise AssertionError(
                f"Operator file access forbidden in tests: {path.name}"
            )
