"""Keep checkout-dependent help rendering in the original capture environment.

The frozen Genre Reveal help includes truncated absolute default paths. Freeze
only their checkout prefix while formatting help; the separate command inventory
still captures the actual defaults after restoration. No application code or
expected snapshot is changed. The locked Typer version vendors Click; its
concrete types preserve the existing Typer testing runner and command identity.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from types import TracebackType
from typing import TypedDict
from typing import Unpack
from unittest.mock import patch

from typer import Typer
from typer import testing
from typer._click import Command
from typer._click import Parameter
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner
from typer.testing import Result


ROOT = Path(__file__).resolve().parents[2]
# Historical display fixture already present in baseline/cli-help.txt.
FROZEN_HELP_ROOT = Path("/Users/uriel.fiori/dev/spotify-manager")


class CaptureOptions(TypedDict):
    """Name the existing Click invocation settings used by the capture.

    Args:
        prog_name: Frozen public command name.
        terminal_width: Frozen terminal width.
        color: Original disabled-color setting.
    """

    prog_name: str
    terminal_width: int
    color: bool


@dataclass
class HelpDefaults(AbstractContextManager[None]):
    """Scope the historical checkout prefix to formatting help only.

    Args:
        command: Selected Click command whose help is being rendered.
        checkout: Actual checkout prefix to substitute before terminal truncation.
        enabled: Whether this invocation requests help rather than execution.
    """

    command: Command
    checkout: Path
    enabled: bool = True
    _originals: list[tuple[Parameter, Path]] = field(default_factory=list, init=False)

    def __enter__(self) -> None:
        """Bind display paths only for checkout-relative Path defaults."""
        if not self.enabled:
            return
        for parameter in self.command.params:
            self._bind(parameter)

    def _bind(self, parameter: Parameter) -> None:
        default = parameter.default
        if not isinstance(default, Path) or not default.is_relative_to(self.checkout):
            return
        self._originals.append((parameter, default))
        parameter.default = FROZEN_HELP_ROOT / default.relative_to(self.checkout)

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore exact default objects before parameter metadata is captured.

        Args:
            kind: Original rendering failure type, if any.
            error: Original failure, which remains unsuppressed.
            traceback: Original rendering traceback.
        """
        for parameter, default in self._originals:
            parameter.default = default
        self._originals.clear()


class SnapshotRunner:
    """Preserve Typer's fresh command conversion with fixed help display paths.

    Args:
        checkout: Actual checkout prefix; defaults to this capture's repository.
    """

    def __init__(self, checkout: Path = ROOT) -> None:
        """Create the original reusable Click test runner.

        Args:
            checkout: Actual repository root used by absolute option defaults.
        """
        self.checkout = checkout
        self._runner = CliRunner()

    def invoke(
        self, app: Typer, args: list[str], **options: Unpack[CaptureOptions]
    ) -> Result:
        """Render help in its frozen environment without changing command execution.

        Args:
            app: Original Typer application, converted afresh as before.
            args: Original help or canned-example arguments.
            **options: Existing explicit Click capture settings.

        Returns:
            Original Click result with exact default objects already restored.
        """
        command = get_command(app)
        selected = _help_command(command, args)
        # The SDK runner resolves a command internally. Bind its own fresh command
        # so the formatting scope and the invoked object have the same identity.
        with (
            patch.object(testing, "_get_command", return_value=command),
            HelpDefaults(selected, self.checkout, enabled="--help" in args),
        ):
            return self._runner.invoke(app, args, **options)


def _help_command(command: Command, args: list[str]) -> Command:
    if isinstance(command, TyperGroup) and args:
        return command.commands.get(args[0], command)
    return command
