"""Prevent fixed policy, workflow and ordinary I/O callback dependencies."""

import ast
from pathlib import Path

import pytest

from tests.support.callback_paths import callable_types
from tests.support.callback_paths import callback_uses
from tests.support.callback_paths import module_trees
from tests.support.callback_policy import callback_reason


ROOT = Path(__file__).resolve().parents[2]


def test_callback_dependencies_have_a_documented_hook_reason() -> None:
    """Require named execution paths across the entire production package."""
    modules = module_trees(ROOT)
    known = callable_types(modules)
    violations = []
    for module, tree in modules.items():
        violations.extend(_prohibited_dependencies(module, tree, known))
    assert violations == []


def _prohibited_dependencies(
    module: str, tree: ast.Module, known: set[str]
) -> list[str]:
    violations = []
    for use in callback_uses(ast.unparse(tree), module, known):
        if callback_reason(use) is None:
            violations.append(f"{use.owner}:{use.parameter}")
    return violations


@pytest.mark.parametrize(
    "declaration",
    [
        "def execute(load: Callable[[], object]) -> None: pass",
        "def execute(operation: Callable[[], object]) -> None: pass",
        "class Dependencies:\n    callback: Callable[[], object]",
        "class Dependencies:\n    select: Callable[[object], bool]",
        "type Reader = Callable[[], object]\ndef execute(read: Reader) -> None: pass",
        "class Reader(Protocol):\n    def __call__(self) -> object: ...\n"
        "def execute(read: Reader) -> None: pass",
    ],
)
def test_callback_guard_rejects_hidden_execution(declaration: str) -> None:
    """Reject direct callbacks, type aliases and callable protocols.

    Args:
        declaration: Intentionally prohibited dependency declaration.
    """
    source = "from typing import Callable, Protocol\n" + declaration
    known = callable_types({"example": ast.parse(source)})
    uses = callback_uses(source, "example", known)
    assert uses
    assert all(callback_reason(use) is None for use in uses)


def test_callback_guard_resolves_imported_aliases() -> None:
    """Keep a renamed callback type from concealing an ordinary I/O dependency."""
    declarations = "from typing import Callable\ntype Reader = Callable[[], object]"
    source = (
        "from example.types import Reader as Fetch\n"
        "def execute(load: Fetch) -> None: pass"
    )
    modules = {
        "example.types": ast.parse(declarations),
        "example.run": ast.parse(source),
    }
    uses = callback_uses(source, "example.run", callable_types(modules))
    assert len(uses) == 1
    assert callback_reason(uses[0]) is None


@pytest.mark.parametrize(
    "parameter, annotation",
    [
        ("clock", "Callable[[], datetime]"),
        ("cancel_check", "Callable[[], bool]"),
        ("echo", "Callable[[str], None]"),
        ("operation", "Callable[[], object]"),
        ("choose", "ReleaseChoiceReader"),
    ],
)
def test_callback_guard_allows_real_operator_and_runtime_hooks(
    parameter: str, annotation: str
) -> None:
    """Retain the hooks whose values originate outside fixed execution rules.

    Args:
        parameter: Genuine hook role.
        annotation: Hook's executable type.
    """
    source = (
        "from typing import Callable\n"
        "type ReleaseChoiceReader = Callable[[object], str]\n"
        f"def retry_call({parameter}: {annotation}) -> None: pass"
    )
    uses = callback_uses(
        source, "example", callable_types({"example": ast.parse(source)})
    )
    assert len(uses) == 1
    assert callback_reason(uses[0])


def test_callback_guard_resolves_reexported_aliases() -> None:
    """Follow public type reexports before classifying a dependency as data."""
    declarations = "from typing import Callable\ntype Reader = Callable[[], object]"
    export = "from example.types import Reader as PublicReader"
    source = "from example import PublicReader\ndef execute(load: PublicReader): pass"
    modules = {
        "example.types": ast.parse(declarations),
        "example": ast.parse(export),
        "example.run": ast.parse(source),
    }
    uses = callback_uses(source, "example.run", callable_types(modules))
    assert len(uses) == 1
    assert callback_reason(uses[0]) is None
