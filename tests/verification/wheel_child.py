"""Inspect the built distribution without importing application code from checkout."""

import inspect
import sys
from importlib.metadata import distribution
from pathlib import Path
from sysconfig import get_path
from types import ModuleType

from tests.verification.network import install_network_guard


def _isolate_imports(site: Path, checkout: Path) -> None:
    paths = [str(site)]
    dependencies = {
        Path(get_path("purelib")).resolve(),
        Path(get_path("platlib")).resolve(),
    }
    for value in sys.path:
        resolved = Path(value).resolve()
        if value and (
            resolved in dependencies or not resolved.is_relative_to(checkout)
        ):
            paths.append(value)
    sys.path[:] = paths


def _check_entrypoints() -> None:
    from typer import Typer
    from typer.core import TyperGroup
    from typer.main import get_command
    from typer.testing import CliRunner

    entries = {}
    for entry in distribution("spotify-manager").entry_points:
        if entry.group == "console_scripts":
            entries[entry.name] = entry
    assert set(entries) == {"spotify-manager", "spotify-api"}
    cli = entries["spotify-manager"].load()
    assert isinstance(cli, Typer)
    group = get_command(cli)
    assert isinstance(group, TyperGroup) and len(group.commands) == 44
    result = CliRunner().invoke(cli, ["--help"], prog_name="spotify-manager")
    assert result.exit_code == 0, result.output
    server = entries["spotify-api"].load()
    assert callable(server)
    parameters = inspect.signature(server).parameters
    assert {name: value.default for name, value in parameters.items()} == {
        "host": "127.0.0.1",
        "port": 8000,
    }


def _check_module_origins(site: Path) -> None:
    for name, module in tuple(sys.modules.items()):
        if not name.startswith("spotify_manager"):
            continue
        assert isinstance(module, ModuleType), name
        _check_module_origin(module, site)


def _check_module_origin(module: ModuleType, site: Path) -> None:
    spec = module.__spec__
    assert spec is not None, module.__name__
    if spec.origin is not None:
        assert Path(spec.origin).resolve().is_relative_to(site), module.__name__
        return
    assert spec.submodule_search_locations, module.__name__
    for path in spec.submodule_search_locations:
        assert Path(path).resolve().is_relative_to(site), module.__name__


def main() -> int:
    """Check real imports, entry points, routes and packaged frontend presence.

    Returns:
        Zero after successful isolated distribution checks.

    Raises:
        AssertionError: Code escaped the wheel or a preserved surface is missing.
    """
    site, checkout = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    install_network_guard()
    _isolate_imports(site, checkout)
    import spotify_manager

    assert spotify_manager.__file__ is not None
    assert Path(spotify_manager.__file__).resolve().is_relative_to(site)
    _check_entrypoints()
    from spotify_manager import api

    assert len(api.app.routes) == 127
    from spotify_manager import web

    assert len(api.app.routes) == 134  # Web wraps the same app, adding seven routes.
    assert vars(web)["app"] is api.app
    assert (site / "spotify_manager/frontend/index.html").is_file()
    assert (site / "spotify_manager/frontend/genre-reveal.html").is_file()
    _check_module_origins(site)
    print("Wheel imports, 44 commands, 134 wrapped routes and both entry points pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
