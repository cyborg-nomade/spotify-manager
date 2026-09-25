"""Keep policy imports independent of runtime services and boundary models."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "spotify_manager" / "domain"
ALLOWED_IMPORTS = {
    "collections",
    "dataclasses",
    "datetime",
    "enum",
    "math",
    "re",
    "typing",
    "unidecode",
    "spotify_manager.domain",
}
IMPORT_SMOKE = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
for name in ('albums', 'artists', 'completion', 'history', 'progression', 'releases'):
    importlib.import_module('spotify_manager.domain.' + name)
for name in sys.modules:
    assert not name.startswith(('spotipy', 'requests', 'httpx', 'pydantic', 'fastapi'))
    assert not name.startswith(('spotify_manager.settings', 'spotify_manager.client'))
    assert not name.startswith(('spotify_manager.routines', 'spotify_manager.core'))
    assert not name.startswith('spotify_manager.models')
    assert not name.startswith('spotify_manager.loaders_savers')
"""


def _import_roots(tree: ast.Module) -> set[str]:
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            result.add(node.module or "")
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=str)
def test_domain_imports_stay_inward(path: Path) -> None:
    """Allow pure value utilities while rejecting application and SDK dependencies.

    Args:
        path: Domain source module under inspection.
    """
    imports = _import_roots(ast.parse(path.read_text()))
    for name in imports:
        assert _allowed_import(name), name


def test_domain_imports_without_application_startup() -> None:
    """Import every policy in a fresh interpreter without application fixtures."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", IMPORT_SMOKE, str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def _allowed_import(name: str) -> bool:
    for root in ALLOWED_IMPORTS:
        if name == root or name.startswith(root + "."):
            return True
    return False
