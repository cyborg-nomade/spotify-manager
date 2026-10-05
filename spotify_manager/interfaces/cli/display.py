"""Console and progress resources owned by a CLI invocation."""

from dataclasses import dataclass

from rich.console import Console
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import SpinnerColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text


@dataclass(frozen=True)
class ConsoleDisplay:
    """Provide terminal rendering and operator interaction constructors.

    Args:
        create_console: Console constructor supplied by the CLI edge.
        create_table: Table constructor supplied by the CLI edge.
        create_text: Styled text constructor supplied by the CLI edge.
        prompt: Operator prompt implementation.
    """

    create_console: type[Console]
    create_table: type[Table]
    create_text: type[Text]
    prompt: type[Prompt] = Prompt


@dataclass(frozen=True)
class ProgressDisplay:
    """Provide the existing terminal progress layout constructors.

    Args:
        create_progress: Progress display constructor.
        bar_column: Progress bar constructor.
        spinner_column: Spinner constructor.
        text_column: Description column constructor.
        time_column: Elapsed-time column constructor.
        complete_column: Optional completed-count column constructor.
    """

    create_progress: type[Progress]
    bar_column: type[BarColumn]
    spinner_column: type[SpinnerColumn]
    text_column: type[TextColumn]
    time_column: type[TimeElapsedColumn]
    complete_column: type[MofNCompleteColumn] = MofNCompleteColumn
