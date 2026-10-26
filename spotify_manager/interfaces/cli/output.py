"""Named Typer output for command adapters and client diagnostics."""

from dataclasses import dataclass

import typer
from rich.console import Console
from rich.status import Status


class TyperOutput:
    """Preserve Typer's original terminal and stream handling."""

    def echo(self, message: str) -> None:
        """Present one unchanged command message.

        Args:
            message: Complete original text.
        """
        typer.echo(message)


TYPER_OUTPUT = TyperOutput()


@dataclass(frozen=True)
class ConsoleOutput:
    """Present messages through a caller-owned Rich console.

    Args:
        console: Existing command console.
    """

    console: Console

    def echo(self, message: str) -> None:
        """Print the original message with the console's existing settings.

        Args:
            message: Complete original text and Rich markup.
        """
        self.console.print(message)


@dataclass(frozen=True)
class StatusOutput:
    """Update a Rich status display through its named framework owner.

    Args:
        status: Existing command status display.
    """

    status: Status

    def echo(self, message: str) -> None:
        """Update the original spinner text.

        Args:
            message: Complete original status description.
        """
        self.status.update(message)
