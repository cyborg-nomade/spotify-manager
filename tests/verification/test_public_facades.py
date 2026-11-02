"""Retain public callable names from the original pre-refactor source inventory."""

import importlib
import json
from pathlib import Path
from typing import TypedDict
from typing import cast

import pytest


ROOT = Path(__file__).resolve().parents[2]
# Item 7a's approved removal of function-valued Python hooks, not new retirements.
HOOK_MIGRATIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("spotify_manager.core.state.compat", "routine_state"): (
        "spotify_manager.core.state.compat",
        "routine_state_from",
    ),
    ("spotify_manager.routines.analyse_library", "prepare_export_resource"): (
        "spotify_manager.application.library_analysis_export",
        "prepare_export_resource",
    ),
    ("spotify_manager.routines.analyse_library", "spotify_call"): (
        "spotify_manager.infrastructure.library_analysis_retry",
        "LibraryRetry",
    ),
    ("spotify_manager.routines.review_album_limits", "retry_spotify_server_errors"): (
        "spotify_manager.infrastructure.spotify.retry",
        "SpotifyRetries",
    ),
}


class SourceInventory(TypedDict):
    """Name the original module-level function inventory field.

    Args:
        function_call_references: Frozen source paths, function names and references.
    """

    function_call_references: dict[str, list[str]]


def _public_callables() -> list[tuple[str, str]]:
    path = ROOT / "docs/refactor/baseline/source-inventory.json"
    inventory = cast(SourceInventory, json.loads(path.read_text()))
    entries = []
    for location in inventory["function_call_references"]:
        source, name = location.rsplit(":", 1)
        if source.startswith("spotify_manager/") and not name.startswith("_"):
            entries.append((source.removesuffix(".py").replace("/", "."), name))
    return sorted(entries)


@pytest.mark.parametrize("module,name", _public_callables())
def test_original_callable_is_retained_or_has_explicit_hook_migration(
    module: str, name: str
) -> None:
    """Guard every original callable with only the four approved hook migrations.

    Args:
        module: Original module path from the immutable source inventory.
        name: Public module-level callable that existed before extraction.
    """
    owner = importlib.import_module(module)
    migration = HOOK_MIGRATIONS.get((module, name))
    if migration is not None:
        replacement = importlib.import_module(migration[0])
        assert callable(getattr(replacement, migration[1]))
        assert not hasattr(owner, name)
        return
    assert callable(getattr(owner, name)), f"{module}.{name}"
