"""Exercise the default mypy configuration against good and bad business code."""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INVALID = """from typing import Any
from nonexistent_quality_probe_sdk import Datum

def untyped(value):
    return value

def dynamic(value: Any) -> Any:
    return value

def unparameterized(value: list) -> list:
    return value

def missing_sdk(value: Datum) -> Datum:
    return value
"""
VALID = """def display(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value

async def preserve_result[T](value: T) -> T:
    return value
"""


def _check_source(
    root: Path, source: str, layer: str
) -> subprocess.CompletedProcess[str]:
    path = root / "spotify_manager" / layer / "probe.py"
    path.parent.mkdir(parents=True)
    path.write_text(source)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(ROOT / "pyproject.toml"),
            "--no-incremental",
            str(path.relative_to(root)),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_default_business_typing_rejects_any_and_missing_imports(
    tmp_path: Path, layer: str
) -> None:
    """Prove strict settings apply without an optional command-line strict flag.

    Args:
        tmp_path: Disposable business module, never executed.
        layer: Business package whose default configuration must be strict.
    """
    result = _check_source(tmp_path, INVALID, layer)
    assert result.returncode == 1, result.stderr
    for code in (
        "no-untyped-def",
        "explicit-any",
        "type-arg",
        "import-not-found",
        "no-any-unimported",
    ):
        assert f"[{code}]" in result.stdout, result.stdout


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_default_business_typing_accepts_narrowing_and_generic_results(
    tmp_path: Path, layer: str
) -> None:
    """Keep precise async return types and ordinary guard-clause narrowing usable.

    Args:
        tmp_path: Disposable typed business module, never executed.
        layer: Business package whose precise typing must remain usable.
    """
    result = _check_source(tmp_path, VALID, layer)
    assert result.returncode == 0, result.stdout + result.stderr
