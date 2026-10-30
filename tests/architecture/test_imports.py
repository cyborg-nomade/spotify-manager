"""Prove the import guard rejects aliases and relative dependency escapes."""

from graphlib import CycleError
from graphlib import TopologicalSorter
from pathlib import Path

import pytest

from tests.architecture.imports import containing_module
from tests.architecture.imports import dependency_graph
from tests.architecture.imports import import_references
from tests.architecture.imports import module_name
from tests.architecture.imports import private_routine_references


@pytest.mark.parametrize(
    "source",
    [
        "from spotify_manager.infrastructure import files as store",
        "from ..infrastructure import files as store",
        "import spotify_manager.infrastructure.files as store",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n from ..infrastructure import files",
        "def deferred():\n from ..infrastructure import files",
    ],
)
def test_resolves_outward_imports(source: str) -> None:
    """Recognize absolute and deferred imports before executing any source.

    Args:
        source: Deliberately invalid application dependency.
    """
    imports = import_references(source, "spotify_manager.application")
    names = [item.name for item in imports]
    assert "spotify_manager.infrastructure.files" in names


@pytest.mark.parametrize(
    "source",
    [
        "from spotify_manager.routines.family import _execute as run",
        "from ..routines.family import _execute as run",
        "import spotify_manager.routines.family as old\nold._execute()",
        "import spotify_manager.routines.family\n"
        "spotify_manager.routines.family._execute()",
        "from spotify_manager import routines as old\nold.family._execute()",
        "from spotify_manager.routines import family as old\nold._execute()",
    ],
)
def test_rejects_private_routine_borrowing(source: str) -> None:
    """Catch imported private helpers and qualified access through aliases.

    Args:
        source: Deliberately private cross-routine reference.
    """
    assert private_routine_references(source, "spotify_manager.interfaces.example") == [
        "spotify_manager.routines.family._execute"
    ]


def test_own_private_helpers_and_public_compatibility_are_allowed() -> None:
    """Keep ordinary module internals and supported public SDK edges usable."""
    source = "from spotify_manager.routines import family\nfamily._execute()"
    assert private_routine_references(source, "spotify_manager.routines.family") == []
    assert (
        private_routine_references(source.replace("_execute", "execute"), "other") == []
    )


def test_import_graph_resolves_symbols_packages_and_cycles(tmp_path: Path) -> None:
    """A relative alias cycle must be visible to the standard-library graph check.

    Args:
        tmp_path: Disposable source package, never imported.
    """
    package = tmp_path / "spotify_manager/application"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "first.py").write_text("from .second import execute as run")
    (package / "second.py").write_text("from . import first as source")
    graph = dependency_graph(tmp_path, "application")
    with pytest.raises(CycleError):
        tuple(TopologicalSorter(graph).static_order())
    assert containing_module("external.client", set(graph)) is None
    assert (
        module_name(package / "__init__.py", tmp_path) == "spotify_manager.application"
    )


def test_relative_import_cannot_escape_package() -> None:
    """Invalid source imports fail explicitly instead of disappearing from the graph."""
    with pytest.raises(ImportError):
        import_references("from ...outside import client", "spotify_manager.domain")
