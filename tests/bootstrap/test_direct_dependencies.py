"""Guard direct use-case wiring and startup import order without live services."""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.dependency_paths import domain_functions
from tests.support.dependency_paths import dynamic_facade_bindings
from tests.support.dependency_paths import facade_forwarders
from tests.support.dependency_paths import forwarding_functions
from tests.support.dependency_paths import forwarding_references
from tests.support.dependency_paths import injected_policies
from tests.support.dependency_paths import legacy_callable_names


ROOT = Path(__file__).resolve().parents[2]


def _internal_paths() -> list[Path]:
    paths: list[Path] = []
    for directory in ("bootstrap", "infrastructure", "interfaces"):
        paths.extend((ROOT / "spotify_manager" / directory).rglob("*.py"))
    return sorted(paths)


def test_default_dependencies_do_not_reference_execution_facades() -> None:
    """Reject inward execution through legacy wrappers across every feature family."""
    prohibited = facade_forwarders(ROOT)
    assert len(prohibited) >= 70
    violations = []
    for path in _internal_paths():
        for reference in forwarding_references(path.read_text(), prohibited):
            violations.append(f"{path.relative_to(ROOT)}:{reference}")
    assert violations == []


@pytest.mark.parametrize(
    "source",
    [
        "from spotify_manager.routines.family import run as execute\nexecute()",
        "from spotify_manager.routines import family as old\nold.run()",
        "import spotify_manager.routines.family as old\ncallback = old.run",
        "from spotify_manager import routines as old\nold.family.run()",
    ],
)
def test_guard_recognizes_aliased_and_deferred_facade_bindings(source: str) -> None:
    """Prove the guard catches direct imports, aliases and deferred callbacks.

    Args:
        source: An intentionally invalid dependency binding.
    """
    assert forwarding_references(source, {"spotify_manager.routines.family.run"})


def test_guard_distinguishes_injected_callables_from_imported_operations() -> None:
    """An injected retry operation is not a reference to a same-named import."""
    source = """from spotify_manager.bootstrap.family import run as operation

def execute():
    return operation()

def retry(operation, description):
    return operation()
"""
    assert forwarding_functions(source, "legacy") == {"legacy.execute"}


def test_guard_allows_concrete_sdk_leaves() -> None:
    """SDK reads remain valid dependencies while their source paths stay frozen."""
    source = "from spotify_manager.routines.family import read_page\nread_page()"
    assert forwarding_references(source, {"spotify_manager.routines.family.run"}) == []


@pytest.mark.parametrize(
    "modules",
    [
        ("spotify_manager.api", "spotify_manager.main"),
        (
            "spotify_manager.infrastructure.discography_observations",
            "spotify_manager.api",
        ),
        ("spotify_manager.infrastructure.legacy.dated_history", "spotify_manager.main"),
        ("spotify_manager.interfaces.operations.legacy_library", "spotify_manager.api"),
        ("spotify_manager.processors.total_albums_processor", "spotify_manager.main"),
        ("spotify_manager.bootstrap.legacy_library", "spotify_manager.api"),
        ("spotify_manager.interfaces.sauvignon_operations", "spotify_manager.main"),
    ],
)
def test_feature_composition_imports_in_a_fresh_process(
    modules: tuple[str, str],
) -> None:
    """Detect composition cycles masked by the test process's prior imports.

    Args:
        modules: Two supported entry modules imported in the specified order.
    """
    script = _import_script(modules)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_concrete_dependencies_do_not_lookup_facade_functions() -> None:
    """Require explicit implementation bindings instead of mutable facade lookups."""
    callables = legacy_callable_names(ROOT)
    violations = []
    for path in _internal_paths():
        for reference in dynamic_facade_bindings(path.read_text(), callables):
            violations.append(f"{path.relative_to(ROOT)}:{reference}")
    assert violations == []


def test_guard_rejects_reexported_function_lookup() -> None:
    """Detect a facade's file-helper alias even when its implementation is elsewhere."""
    callables = legacy_callable_names(ROOT)
    name = "spotify_manager.processors.library_lookups.load_album_tracks_cache"
    assert name in callables
    source = (
        "from spotify_manager.processors import library_lookups as old\n"
        "old.load_album_tracks_cache()"
    )
    assert dynamic_facade_bindings(source, callables)


def _import_script(modules: tuple[str, str]) -> str:
    statements = ["import importlib"]
    for module in modules:
        statements.append(f"importlib.import_module({module!r})")
    return "; ".join(statements)


def test_fixed_domain_policies_are_called_directly() -> None:
    """Keep fixed business rules visible at the application call site."""
    policies = domain_functions(ROOT)
    violations = []
    for path in _business_paths():
        for reference in injected_policies(path.read_text(), policies):
            violations.append(f"{path.relative_to(ROOT)}:{reference}")
    assert violations == []


@pytest.mark.parametrize(
    "source",
    [
        "from spotify_manager.domain.calendar import cutoff\nSelection(cutoff)",
        "from spotify_manager.domain import calendar as rules\nSelection(rules.cutoff)",
        "import spotify_manager.domain.calendar as rules\nSelection(rule=rules.cutoff)",
        "from spotify_manager.domain.calendar import cutoff\npartial(cutoff, today)",
    ],
)
def test_policy_guard_rejects_aliased_and_deferred_rules(source: str) -> None:
    """Reject the indirection that hid fixed business rules in constructors.

    Args:
        source: Intentionally invalid domain-rule dependency injection.
    """
    assert injected_policies(source, {"spotify_manager.domain.calendar.cutoff"})


@pytest.mark.parametrize(
    "source",
    [
        "from spotify_manager.domain.calendar import cutoff\nSelection(cutoff(today))",
        "from spotify_manager.domain.calendar import cutoff\nsorted(items, key=cutoff)",
        "from external import clock\nSelection(clock)",
        "from spotify_manager.domain.calendar import cutoff\n"
        "def build(cutoff):\n    return Selection(cutoff)",
    ],
)
def test_policy_guard_allows_decisions_collection_keys_and_real_clocks(
    source: str,
) -> None:
    """Preserve normal function calls, Python collection idioms and I/O callbacks.

    Args:
        source: Valid fixed-rule call or genuine external observation.
    """
    assert injected_policies(source, {"spotify_manager.domain.calendar.cutoff"}) == []


def _business_paths() -> list[Path]:
    paths = []
    for directory in ("application", "bootstrap", "infrastructure"):
        paths.extend((ROOT / "spotify_manager" / directory).rglob("*.py"))
    return sorted(paths)
