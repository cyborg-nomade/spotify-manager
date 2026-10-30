"""Keep help snapshots independent of checkout paths without changing real defaults."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import pytest
from typer import Option
from typer import Typer
from typer.core import TyperCommand
from typer.core import TyperOption
from typer.main import get_command

from docs.refactor.check_interfaces import compare_interfaces
from docs.refactor.cli_capture import FROZEN_HELP_ROOT
from docs.refactor.cli_capture import HelpDefaults
from docs.refactor.cli_capture import SnapshotRunner


FOREIGN_ROOT = Path("/foreign/checkout")
FOREIGN_DEFAULT = FOREIGN_ROOT / "spotify_manager/files/example.json"


def _display_path(
    path: Annotated[Path, Option("--path")] = FOREIGN_DEFAULT,
) -> None:
    print(path)


def test_foreign_checkout_help_uses_the_original_rendering_environment() -> None:
    """Freeze only display paths while command execution and metadata stay original."""
    app = Typer()
    # Typer's external registration API requires the command callback.
    app.command()(_display_path)
    runner = SnapshotRunner(FOREIGN_ROOT)
    result = runner.invoke(
        app, ["--help"], prog_name="example", terminal_width=100, color=False
    )
    assert result.exit_code == 0, result.exception
    assert str(FROZEN_HELP_ROOT) in result.output
    command = get_command(app)
    assert command.params[0].default is FOREIGN_DEFAULT
    executed = runner.invoke(
        app, [], prog_name="example", terminal_width=100, color=False
    )
    assert executed.exit_code == 0, executed.exception
    assert executed.output == f"{FOREIGN_DEFAULT}\n"


@pytest.mark.parametrize("filename", ["original.json", "changed.json"])
def test_help_environment_retains_the_actual_relative_default(filename: str) -> None:
    """A logical default change stays visible instead of being replaced by a fixture.

    Args:
        filename: Original or deliberately changed relative path.
    """
    original = FOREIGN_ROOT / "spotify_manager/files" / filename
    option = TyperOption(param_decls=["--path"], default=original)
    command = TyperCommand("example", params=[option])
    with HelpDefaults(command, FOREIGN_ROOT):
        assert option.default == FROZEN_HELP_ROOT / "spotify_manager/files" / filename
    assert option.default is original


@pytest.mark.parametrize(
    "default",
    [Path("relative.json"), Path("/outside/other.json"), "literal default"],
)
def test_unrelated_defaults_are_never_rewritten(default: Path | str) -> None:
    """Limit the display fixture to absolute paths within the inspected checkout.

    Args:
        default: Relative, external or non-Path original value.
    """
    option = TyperOption(param_decls=["--path"], default=default)
    with HelpDefaults(TyperCommand("example", params=[option]), FOREIGN_ROOT):
        assert option.default is default
    assert option.default is default


def test_rendering_failure_restores_exact_original_objects() -> None:
    """Keep a failed capture from changing subsequent metadata or execution."""
    option = TyperOption(param_decls=["--path"], default=FOREIGN_DEFAULT)
    with pytest.raises(RuntimeError, match="rendering failed"):
        with HelpDefaults(TyperCommand("example", params=[option]), FOREIGN_ROOT):
            raise RuntimeError("rendering failed")
    assert option.default is FOREIGN_DEFAULT


def _copy_capture_sources(source: Path, checkout: Path) -> None:
    paths = list((source / "spotify_manager").rglob("*.py"))
    paths.extend(
        [
            source / "docs/refactor/capture_baseline.py",
            source / "docs/refactor/cli_capture.py",
            source / ".github/scripts/nightly_refresh.py",
        ]
    )
    for path in paths:
        target = checkout / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def test_complete_capture_matches_from_a_foreign_checkout(tmp_path: Path) -> None:
    """Reproduce the Linux path mismatch without copying operator data or credentials.

    Args:
        tmp_path: Different source checkout prefix for an isolated subprocess.
    """
    source = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "different-checkout"
    _copy_capture_sources(source, checkout)
    output = tmp_path / "captured"
    result = subprocess.run(
        [
            sys.executable,
            str(checkout / "docs/refactor/capture_baseline.py"),
            "--write",
            "--output",
            str(output),
        ],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert compare_interfaces(output) == 11
