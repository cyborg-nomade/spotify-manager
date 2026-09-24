"""Capture offline interface and source inventories for refactor item 1.

Run with the locked project Python. --check is read-only; --write explicitly
replaces the chosen output directory's generated files. This is audit tooling,
not an application entry point or a substitute for behavioral tests.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
import tempfile
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "baseline"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def normalized(value: Any) -> Any:
    """Remove checkout-specific paths without changing values or list order."""
    if isinstance(value, str):
        return value.replace(str(ROOT), "<REPO>")
    if isinstance(value, Path):
        return normalized(str(value))
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalized(item) for item in value]
    return value


def as_json(value: Any) -> str:
    """Use deterministic JSON while preserving ordered arrays."""
    return json.dumps(normalized(value), indent=2, sort_keys=True) + "\n"


def terminal_text(value: str) -> str:
    """Remove ANSI codes and insignificant end-of-line terminal padding."""
    return re.sub(r"[ \t]+(?=\n|$)", "", ANSI.sub("", value))


@contextmanager
def isolated_runtime() -> Iterator[None]:
    """Avoid reading operator .env/secrets or invoking real external services."""
    old_cwd = Path.cwd()
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    with tempfile.TemporaryDirectory(prefix="spotify-contract-") as temporary:
        environment = {
            "SPOTIPY_CLIENT_ID": "fixture-client",
            "SPOTIPY_CLIENT_SECRET": "fixture-secret",
            "SPOTIPY_REDIRECT_URI": "http://127.0.0.1:8080/callback",
            "ALBUMS_TO_ADD": "10",
            "LIMIT": "50",
            "APP_PASSWORD": "fixture-password",
            "SPOTIFY_MANAGER_STATE_BACKEND": "local",
            "SPOTIFY_MANAGER_STATE_LOCAL_PATH": f"{temporary}/state.json",
            "SPOTIFY_MANAGER_DATA_BACKEND": "local",
            "SPOTIFY_MANAGER_DATA_LOCAL_ROOT": f"{temporary}/data",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "100",
        }
        try:
            os.chdir(temporary)
            with (
                patch.dict(os.environ, environment, clear=True),
                patch(
                    "socket.socket.connect",
                    side_effect=RuntimeError("network forbidden"),
                ),
                patch(
                    "socket.socket.connect_ex",
                    side_effect=RuntimeError("network forbidden"),
                ),
                patch("socket.getaddrinfo", side_effect=RuntimeError("DNS forbidden")),
            ):
                yield
        finally:
            os.chdir(old_cwd)
            sys.dont_write_bytecode = old_bytecode


def source_inventory() -> dict[str, Any]:
    """Record static evidence; call references are not a resolved call graph."""
    files = sorted((ROOT / "spotify_manager").rglob("*.py"))
    files.append(ROOT / ".github/scripts/nightly_refresh.py")
    imports: dict[str, list[str]] = {}
    spotify: dict[str, list[str]] = {}
    environment: list[dict[str, str | int]] = []
    paths: dict[str, dict[str, str]] = {}
    calls: dict[str, list[str]] = {}
    urls: dict[str, list[str]] = {}
    retry_calls = []
    for path in files:
        relative = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text())
        imported: set[str] = set()
        methods = set()
        literals = set()
        path_definitions = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("spotify_manager"):
                    imported.update(
                        f"{node.module}.{alias.name}" for alias in node.names
                    )
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("spotify_manager")
                )
            if isinstance(node, ast.Call):
                expression = ast.unparse(node.func)
                if expression.endswith(("retry_spotify_server_errors", "spotify_call")):
                    retry_calls.append(
                        {
                            "source": relative,
                            "line": node.lineno,
                            "expression": ast.unparse(node),
                        }
                    )
                if expression.startswith(("sp.", "spotify.", "client.")):
                    methods.add(expression)
                if expression in {"os.getenv", "os.environ.get"}:
                    environment.append(
                        {
                            "source": relative,
                            "line": node.lineno,
                            "expression": ast.unparse(node),
                        }
                    )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith(("https://", "http://")):
                    literals.add(node.value)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and any(
                        token in target.id for token in ("PATH", "DIR", "FILENAME")
                    ):
                        path_definitions[target.id] = ast.unparse(node.value)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls[f"{relative}:{node.name}"] = sorted(
                    {
                        ast.unparse(child.func)
                        for child in ast.walk(node)
                        if isinstance(child, ast.Call)
                    }
                )
        imports[relative] = sorted(imported)
        if methods:
            spotify[relative] = sorted(methods)
        if path_definitions:
            paths[relative] = path_definitions
        if literals:
            urls[relative] = sorted(literals)
    return {
        "internal_imports": imports,
        "external_call_candidates": spotify,
        "environment_reads": environment,
        "path_definitions": paths,
        "function_call_references": calls,
        "url_literals": urls,
        "retry_call_sites": retry_calls,
    }


def spotify_contracts() -> dict[str, Any]:
    """Resolve used SDK methods and direct HTTP calls from source, without I/O."""
    from spotipy import Spotify

    sdk_references: dict[str, list[str]] = {}
    direct_calls = []
    for path in sorted((ROOT / "spotify_manager").rglob("*.py")):
        source = str(path.relative_to(ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and ast.unparse(node.value)
                in {
                    "sp",
                    "spotify",
                    "client",
                    "client()",
                }
                and hasattr(Spotify, node.attr)
                and not node.attr.startswith("_")
            ):
                sdk_references.setdefault(node.attr, []).append(
                    f"{source}:{node.lineno}"
                )
            if not isinstance(node, ast.Call):
                continue
            arguments = node.args
            operation = node.func
            if ast.unparse(operation) == "partial" and arguments:
                operation, arguments = arguments[0], arguments[1:]
            if (
                isinstance(operation, ast.Attribute)
                and operation.attr
                in {
                    "_get",
                    "_post",
                    "_put",
                    "_delete",
                }
                and ast.unparse(operation.value) in {"sp", "spotify", "client"}
            ):
                direct_calls.append(
                    {
                        "source": source,
                        "line": node.lineno,
                        "method": operation.attr[1:].upper(),
                        "endpoint": ast.unparse(arguments[0]) if arguments else None,
                        "expression": ast.unparse(node),
                    }
                )
    implementations = {}
    for name, references in sorted(sdk_references.items()):
        implementation = textwrap.dedent(inspect.getsource(getattr(Spotify, name)))
        tree = ast.parse(implementation)
        implementations[name] = {
            "references": sorted(set(references)),
            "sdk_calls": [
                ast.unparse(node)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ],
        }
    return {
        "sdk_version": version("spotipy"),
        "sdk_methods": implementations,
        "direct_http_calls": direct_calls,
    }


def route_inventory(app: Any, surface: str) -> list[dict[str, Any]]:
    """Include framework and hidden routes as well as OpenAPI operations."""
    result = []
    for route in app.routes:
        endpoint = route.endpoint
        module = endpoint.__module__
        result.append(
            {
                "surface": surface,
                "path": route.path,
                "methods": sorted(route.methods),
                "name": route.name,
                "handler": f"{module}.{endpoint.__name__}",
                "source_line": inspect.getsourcelines(endpoint)[1],
                "include_in_schema": route.include_in_schema,
                "declared_status_code": getattr(route, "status_code", None),
                "response_model": getattr(
                    getattr(route, "response_model", None), "__name__", None
                ),
            }
        )
    return result


def capture_cli(main: Any) -> dict[str, str]:
    """Capture all help pages and a small, explicitly stubbed output sample."""
    from typer.core import TyperGroup
    from typer.main import get_command
    from typer.testing import CliRunner

    from spotify_manager.models.lookups import AlbumEvaluation
    from spotify_manager.models.lookups import ArtistLibraryStats

    command = get_command(main.app)
    if not isinstance(command, TyperGroup):
        raise TypeError("Expected the public CLI to be a command group")
    runner = CliRunner()
    help_pages = []
    commands = []
    with patch.object(main, "hydrate_runtime_library_data", return_value=()):
        for name in [None, *sorted(command.commands)]:
            args = ["--help"] if name is None else [name, "--help"]
            result = runner.invoke(
                main.app,
                args,
                prog_name="spotify-manager",
                terminal_width=100,
                color=False,
            )
            if result.exit_code != 0:
                raise RuntimeError(f"Help failed: {args}: {result.exception}")
            output = terminal_text(result.output)
            help_pages.append(f"$ spotify-manager {' '.join(args)}\n{output}")
            if name is None:
                continue
            child = command.commands[name]
            if child.callback is None:
                raise TypeError(f"Missing callback for {name}")
            commands.append(
                {
                    "name": name,
                    "handler": child.callback.__name__,
                    "help": child.help,
                    "parameters": [
                        {
                            "name": parameter.name,
                            "kind": type(parameter).__name__,
                            "opts": parameter.opts,
                            "secondary_opts": parameter.secondary_opts,
                            "required": parameter.required,
                            "default": parameter.default,
                            "nargs": parameter.nargs,
                            "type": type(parameter.type).__name__,
                            "help": getattr(parameter, "help", None),
                            "is_flag": getattr(parameter, "is_flag", False),
                            "multiple": parameter.multiple,
                        }
                        for parameter in child.params
                    ],
                }
            )
        examples = []
        stats = ArtistLibraryStats(
            artist_name="Example Artist",
            artist_id="artist-id",
            liked_tracks=6,
            saved_releases=2,
            source="spotify-live",
        )
        album = AlbumEvaluation(
            album_name="Example Album",
            album_id="album-id",
            artist_name="Example Artist",
            total_tracks=3,
            liked_tracks=1,
            required_liked_tracks=1,
            liked_ratio=1 / 3,
            threshold=0.5,
            decision="keep",
            tracks=[],
            source="spotify-live",
        )
        # Values below are canned application outputs, not behavioral test oracles.
        with (
            patch.object(main, "client", return_value=object()),
            patch.object(main, "count_artists_in_library", return_value=42),
            patch.object(main, "get_live_artist_library_stats", return_value=stats),
            patch.object(main, "evaluate_album_live", return_value=album),
        ):
            for args in (
                ["count-artists"],
                ["artist-stats", "Example Artist"],
                ["album-decision", "Example Album"],
                ["artist-stats"],
                ["album-decision"],
                ["not-a-command"],
            ):
                result = runner.invoke(
                    main.app,
                    args,
                    prog_name="spotify-manager",
                    terminal_width=100,
                    color=False,
                )
                examples.append(
                    {
                        "argv": args,
                        "exit_code": result.exit_code,
                        "stdout": terminal_text(result.stdout),
                        "stderr": terminal_text(result.stderr),
                    }
                )
    return {
        "cli-help.txt": "\n".join(help_pages).rstrip("\n") + "\n",
        "cli-commands.json": as_json(commands),
        "cli-examples.json": as_json(examples),
    }


def capture_runtime() -> dict[str, str]:
    """Inspect application registrations without running ASGI lifespan/jobs."""
    from spotify_manager import api
    from spotify_manager import main
    from spotify_manager.settings import Settings

    result = capture_cli(main)
    routes = route_inventory(api.app, "api")
    result["openapi.json"] = as_json(api.app.openapi())
    pure_count = len(routes)
    # web imports and mutates the same app; clear its schema cache before capture.
    from spotify_manager import web

    web.app.openapi_schema = None
    web_schema = web.app.openapi()
    pure_schema = json.loads(result["openapi.json"])
    result["web-openapi-additions.json"] = as_json(
        {
            "paths": {
                key: value
                for key, value in web_schema["paths"].items()
                if key not in pure_schema["paths"]
            },
            "schemas": {
                key: value
                for key, value in web_schema["components"]["schemas"].items()
                if key not in pure_schema["components"]["schemas"]
            },
        }
    )
    routes.extend(route_inventory(web.app, "web")[pure_count:])
    result["routes.json"] = as_json(routes)
    result["settings.json"] = as_json(
        {
            "model_config": {
                "env_file": ".env",
                "case_sensitive": Settings.model_config["case_sensitive"],
            },
            "fields": {
                name: {
                    "environment_name": name.upper(),
                    "required": field.is_required(),
                    "default": None if field.is_required() else field.default,
                    "annotation": str(field.annotation),
                    "alias": field.alias,
                    "validation_alias": field.validation_alias,
                }
                for name, field in Settings.model_fields.items()
            },
        }
    )
    result["state-defaults.json"] = as_json(
        {
            name: {
                "default": factory(),
                "validator": f"{validator.__module__}.{validator.__name__}",
            }
            for name, (factory, validator) in api.STATE_NAMESPACE_DEFINITIONS.items()
        }
    )
    return result


def inventory_tables(artifacts: dict[str, str]) -> dict[str, str]:
    """Render complete human-readable registration and dependency checklists."""
    commands = json.loads(artifacts["cli-commands.json"])
    routes = json.loads(artifacts["routes.json"])
    lines = [
        "# Frozen interface checklist",
        "",
        "Generated by `../capture_baseline.py`; see `../README.md` for scope.",
        "Every row must retain its contract during migration. The unchecked",
        "boxes track future migration verification, not missing inventory work.",
        "",
        "## CLI commands",
        "",
        "All 44 commands are captured in `cli-help.txt` and `cli-commands.json`.",
        "Options, positional arguments, flags and defaults in JSON are normative",
        "for this baseline; parameter names below are Python callback names.",
        "",
        "| Migration verified | Command | Callback | Parameters and defaults |",
        "| --- | --- | --- | --- |",
    ]
    for command in commands:
        parameters = (
            "; ".join(
                f"`{item['name']}={item['default']!r}`"
                for item in command["parameters"]
            )
            or "None"
        )
        lines.append(
            f"| [ ] | `{command['name']}` | `{command['handler']}` | {parameters} |"
        )
    lines.extend(
        [
            "",
            "## HTTP routes",
            "",
            "Includes 115 application API routes, four FastAPI framework routes,",
            "and seven web additions. `openapi.json` freezes pure API schemas;",
            "`web-openapi-additions.json` freezes the additional web schemas.",
            "Hidden routes remain in this table. Framework GET/HEAD methods share",
            "one route registration. API-only imports are ungated; importing web",
            "adds the password middleware to the same app. See `../CONTRACTS.md`.",
            "",
            "| Migration verified | Surface | Method | Path | Handler | In schema |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for route in routes:
        handler = route["handler"].rsplit(".", 1)[-1]
        lines.append(
            f"| [ ] | {route['surface']} | {', '.join(route['methods'])} | "
            f"`{route['path']}` | `{handler}` | {route['include_in_schema']} |"
        )
    inventory = json.loads(artifacts["source-inventory.json"])
    dependencies = [
        "# Frozen routine dependencies",
        "",
        "Static import evidence, including imports inside functions. These are",
        "dependencies to account for, not proposed architectural boundaries.",
        "The full package import inventory and per-function call references are",
        "in `source-inventory.json`; dynamic dispatch is not resolved by AST.",
        "",
        "| Routine | Internal imports |",
        "| --- | --- |",
    ]
    for path, imports in inventory["internal_imports"].items():
        if not path.startswith("spotify_manager/routines/"):
            continue
        imports = [item.removeprefix("spotify_manager.") for item in imports]
        dependencies.append(
            f"| `{Path(path).stem}` | "
            + "; ".join(f"`{item}`" for item in imports)
            + " |"
        )
    return {
        "interfaces.md": "\n".join(lines) + "\n",
        "routine-dependencies.md": "\n".join(dependencies) + "\n",
    }


def main() -> None:
    """Write or check a deterministic capture without changing the application."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    sys.path.insert(0, str(ROOT))
    with isolated_runtime():
        artifacts = capture_runtime()
    artifacts["source-inventory.json"] = as_json(source_inventory())
    artifacts["spotify-endpoints.json"] = as_json(spotify_contracts())
    artifacts.update(inventory_tables(artifacts))
    artifacts["tool-versions.json"] = as_json(
        {
            name: version(name)
            for name in (
                "fastapi",
                "starlette",
                "typer",
                "click",
                "rich",
                "pydantic",
                "spotipy",
                "httpx",
                "requests",
                "huggingface-hub",
            )
        }
    )
    mismatches = []
    for name, content in artifacts.items():
        target = output / name
        if args.write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != content:
            mismatches.append(name)
    if mismatches:
        raise SystemExit("Baseline differs: " + ", ".join(mismatches))
    verb = "Wrote" if args.write else "Verified"
    print(f"{verb} {len(artifacts)} offline baseline artifacts in {output}")


if __name__ == "__main__":
    main()
