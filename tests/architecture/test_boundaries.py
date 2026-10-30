"""Enforce inward business dependencies, acyclic features and public routine edges."""

import sys
from graphlib import TopologicalSorter
from pathlib import Path

import pytest

from tests.architecture.imports import dependency_graph
from tests.architecture.imports import import_references
from tests.architecture.imports import module_name
from tests.architecture.imports import private_routine_references


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "spotify_manager"
BUSINESS_IMPORTS = {
    "domain": ("spotify_manager.domain", "unidecode"),
    "application": (
        "spotify_manager.application",
        "spotify_manager.domain",
        "spotify_manager.models",
        "spotify_manager.core.state.models",
        "spotify_manager.core.library_data.models",
        "spotify_manager.utils.growth",
        "spotify_manager.utils.sorting",
        "pydantic",
    ),
}


def _allowed(name: str, layer: str) -> bool:
    if name.partition(".")[0] in sys.stdlib_module_names:
        return True
    for prefix in BUSINESS_IMPORTS[layer]:
        if name == prefix or name.startswith(prefix + "."):
            return True
    return False


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_business_imports_resolve_only_inward(layer: str) -> None:
    """Reject UI, bootstrap, SDK and concrete adapter imports in every spelling.

    Args:
        layer: Business package inspected recursively, including type-only imports.
    """
    violations = []
    for path in sorted((PACKAGE / layer).rglob("*.py")):
        violations.extend(_outward_imports(path, layer))
    assert violations == []


def _outward_imports(path: Path, layer: str) -> list[str]:
    name = module_name(path, ROOT)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    violations = []
    for reference in import_references(path.read_text(), package):
        if not _allowed(reference.name, layer):
            violations.append(f"{name}:{reference.line}: {reference.name}")
    return violations


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_business_feature_graph_is_acyclic(layer: str) -> None:
    """Reject static feature cycles, including relative and type-only edges.

    Args:
        layer: Domain or application dependency graph.
    """
    graph = dependency_graph(ROOT, layer)
    ordered = tuple(TopologicalSorter(graph).static_order())
    assert set(ordered) == set(graph)


def test_routines_never_borrow_another_routines_private_helpers() -> None:
    """Protect compatibility routines against direct and aliased private imports."""
    violations = []
    for path in sorted((PACKAGE / "routines").rglob("*.py")):
        references = private_routine_references(
            path.read_text(), module_name(path, ROOT)
        )
        violations.extend(references)
    assert violations == []


@pytest.mark.parametrize(
    "name",
    [
        "spotify_manager.interfaces.http.handler",
        "spotify_manager.infrastructure.files",
        "spotify_manager.bootstrap.clients",
        "spotify_manager.api.get_client",
        "spotify_manager.main.run",
        "spotify_manager.routines.family.run",
        "spotify_manager.core.state.runtime.get_state_service",
        "httpx.AsyncClient",
        "fastapi.Depends",
    ],
)
def test_allowlist_rejects_every_outward_layer(name: str) -> None:
    """Test the policy used by the source scan with forbidden synthetic imports.

    Args:
        name: Outward dependency forbidden to both business layers.
    """
    assert not _allowed(name, "domain")
    assert not _allowed(name, "application")
