"""Keep unrelated routines independent of one another's private implementations."""

import ast
from pathlib import Path

import pytest


ROUTINES = Path(__file__).parents[2] / "spotify_manager/routines"


def routine_aliases(tree: ast.Module) -> set[str]:
    """Identify direct imported routine module aliases.

    Args:
        tree: Original routine source module.

    Returns:
        Aliases belonging to unrelated routine modules.
    """
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "spotify_manager.routines":
            continue
        for alias in node.names:
            result.add(alias.asname or alias.name)
    return result


@pytest.mark.parametrize("path", sorted(ROUTINES.glob("*.py")), ids=str)
def test_routines_do_not_borrow_private_routine_helpers(path: Path) -> None:
    """Keep compatibility calls public and extracted listening rules independent.

    Args:
        path: Original routine compatibility module.
    """
    tree = ast.parse(path.read_text())
    aliases = routine_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id in aliases:
            assert not node.attr.startswith("_"), f"{path.name}: {ast.unparse(node)}"
