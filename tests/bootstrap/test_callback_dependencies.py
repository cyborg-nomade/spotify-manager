"""Prevent fixed policy, workflow and ordinary I/O callback dependencies."""

import ast
from pathlib import Path

import pytest

from tests.support.callback_arguments import defined_functions
from tests.support.callback_arguments import function_arguments
from tests.support.callback_paths import callable_types
from tests.support.callback_paths import callback_uses
from tests.support.callback_paths import module_trees
from tests.support.callback_policy import callback_reason
from tests.support.callback_policy import function_argument_reason


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
def test_callback_guard_rejects_replaceable_operator_and_runtime_hooks(
    parameter: str, annotation: str
) -> None:
    """Require named owners even for interactions, clocks and retry operations.

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
    assert callback_reason(uses[0]) is None


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


@pytest.mark.parametrize(
    "owner, parameter",
    [
        (
            "spotify_manager.infrastructure.library_analysis_catalog.SpotifyOffsetPages",
            "_method",
        ),
        ("spotify_manager.infrastructure.spotify.events.SpotifyEvents", "_setter"),
    ],
)
def test_callback_guard_retains_only_specific_sdk_bindings(
    owner: str, parameter: str
) -> None:
    """Document exact method captures without enabling a general role exception.

    Args:
        owner: Concrete SDK compatibility leaf.
        parameter: Private field retaining the original bound method.
    """
    from tests.support.callback_paths import CallbackUse

    use = CallbackUse(owner, parameter, "Callable[..., object]", 1)
    assert callback_reason(use)
    renamed = CallbackUse(owner + "Copy", parameter, use.annotation, 1)
    assert callback_reason(renamed) is None


def test_execution_arguments_require_an_external_api_reason() -> None:
    """Reject function values even when dependency annotations conceal them."""
    modules = module_trees(ROOT)
    modules["nightly_refresh"] = ast.parse(
        (ROOT / ".github/scripts/nightly_refresh.py").read_text()
    )
    known = defined_functions(modules)
    violations = []
    for module, tree in modules.items():
        violations.extend(_prohibited_arguments(module, tree, known))
    assert violations == []


@pytest.mark.parametrize(
    "body",
    [
        "execute(fixed)",
        "execute(operation=fixed)",
        "dependencies = Dependencies(fixed)",
        "alias = fixed\nexecute(alias)",
        "execute(lambda: 1)",
    ],
)
def test_argument_guard_rejects_untyped_execution_dependencies(body: str) -> None:
    """Detect callback values independently of parameter and field annotations.

    Args:
        body: Deliberately hidden ordinary execution dependency.
    """
    tree = ast.parse("def fixed() -> int: return 1\n" + body)
    known = defined_functions({"example": tree})
    uses = function_arguments("example", tree, known)
    assert uses
    assert all(function_argument_reason(use) is None for use in uses)


def test_argument_guard_rejects_bound_methods() -> None:
    """Require the named owner instead of its bound execution method."""
    tree = ast.parse(
        "class Worker:\n"
        "    def fixed(self) -> int: return 1\n"
        "    def run(self) -> None: execute(self.fixed)\n"
    )
    uses = function_arguments("example", tree, defined_functions({"example": tree}))
    assert len(uses) == 1
    assert function_argument_reason(uses[0]) is None


def test_argument_guard_ignores_data_shadowing_a_function() -> None:
    """Do not mistake an ordinary parameter for an imported function name."""
    tree = ast.parse(
        "def artist() -> int: return 1\ndef run(artist: str) -> None: execute(artist)\n"
    )
    assert (
        function_arguments("example", tree, defined_functions({"example": tree})) == []
    )


def _prohibited_arguments(module: str, tree: ast.Module, known: set[str]) -> list[str]:
    violations = []
    for use in function_arguments(module, tree, known):
        if function_argument_reason(use) is None:
            violations.append(f"{use.owner}:{use.line}:{use.function}")
    return violations


def test_argument_guard_resolves_a_bound_method_alias() -> None:
    """Keep a local alias from concealing bound-method execution injection."""
    tree = ast.parse(
        "class Worker:\n"
        "    def fixed(self) -> int: return 1\n"
        "    def run(self) -> None:\n"
        "        alias = self.fixed\n"
        "        execute(alias)\n"
    )
    uses = function_arguments("example", tree, defined_functions({"example": tree}))
    assert len(uses) == 1
    assert function_argument_reason(uses[0]) is None


@pytest.mark.parametrize(
    "method, function",
    [
        ("token", "source.token"),
        ("refresh", "source.refresh"),
        ("open_sources", "provisioner.open_sources"),
        ("close", "source.close"),
    ],
)
def test_only_bounded_sdk_work_can_use_the_required_thread_bridge(
    method: str, function: str
) -> None:
    """Keep native Spotify HTTP out of the narrow OAuth/cache thread exemption.

    Args:
        method: Named bounded SDK/cache boundary.
        function: Exact method required by asyncio.to_thread.
    """
    from tests.support.callback_arguments import FunctionArgument

    owner = (
        "spotify_manager.infrastructure.spotify_async.blocking.BlockingOAuth." + method
    )
    use = FunctionArgument(owner, "asyncio.to_thread", "0", function, 1)
    assert function_argument_reason(use)
    forbidden = FunctionArgument(owner, "asyncio.to_thread", "0", "spotify.request", 1)
    assert function_argument_reason(forbidden) is None
