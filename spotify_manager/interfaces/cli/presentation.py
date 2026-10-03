"""Small presentation helpers shared by feature command adapters."""


def progress_description(description: str, dry_run: bool) -> str:
    """Label progress with the original dry-run suffix.

    Args:
        description: The feature's normal progress label.
        dry_run: Whether the command is previewing its changes.

    Returns:
        The label shown by Rich while the command runs.
    """
    if dry_run:
        return description + " (dry run)"
    return description
