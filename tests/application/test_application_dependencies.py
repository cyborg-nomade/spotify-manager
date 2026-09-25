"""Enforce inward imports and startup-free application construction."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "spotify_manager/application"
FORBIDDEN = (
    "spotipy",
    "requests",
    "httpx",
    "fastapi",
    "rich",
    "typer",
    "spotify_manager.bootstrap",
    "spotify_manager.infrastructure",
    "spotify_manager.routines",
    "spotify_manager.processors",
    "spotify_manager.settings",
    "spotify_manager.client",
    "spotify_manager.core.state.runtime",
    "spotify_manager.core.state.compat",
    "spotify_manager.core.library_data.runtime",
)
SMOKE = """
import importlib
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
root = pathlib.Path(sys.argv[1])
for path in (root / 'spotify_manager/application').rglob('*.py'):
    name = '.'.join(path.relative_to(root).with_suffix('').parts)
    importlib.import_module(name)
for name in sys.modules:
    assert not name.startswith(('spotipy', 'requests', 'httpx', 'huggingface_hub'))
    assert not name.startswith(('spotify_manager.settings', 'spotify_manager.client'))
    assert not name.startswith('spotify_manager.bootstrap')
    assert not name.startswith('spotify_manager.infrastructure')
"""


@pytest.mark.parametrize("path", sorted(APPLICATION.rglob("*.py")), ids=str)
def test_application_imports_stay_inward(path: Path) -> None:
    """Reject outward imports from use cases and their contracts.

    Args:
        path: Source module to inspect.
    """
    for node in ast.walk(ast.parse(path.read_text())):
        assert not _forbidden_import(node), (path, ast.unparse(node))


def _forbidden_import(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").startswith(FORBIDDEN)
    if isinstance(node, ast.Import):
        return any(alias.name.startswith(FORBIDDEN) for alias in node.names)
    return False


def test_application_imports_without_bootstrap_or_sdks() -> None:
    """Import every application module without constructing runtime dependencies."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", SMOKE, str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
