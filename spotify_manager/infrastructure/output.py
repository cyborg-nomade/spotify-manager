"""Named console output retaining original positional print behavior."""


class StandardOutput:
    """Write the original values to standard output."""

    def echo(self, *values: object) -> None:
        """Print one original observation.

        Args:
            values: Original positional print arguments.
        """
        print(*values)


STANDARD_OUTPUT = StandardOutput()
