"""Enforce flat, short business code and the package-wide callback-era constraints."""

from pathlib import Path

import pytest

from tests.architecture.structure import structure_violations


PACKAGE = Path(__file__).resolve().parents[2] / "spotify_manager"


def test_source_remains_flat_and_business_functions_stay_short() -> None:
    """Protect every source module, with extra size and indentation checks inward."""
    violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        business = path.relative_to(PACKAGE).parts[0] in {"domain", "application"}
        for violation in structure_violations(path.read_text(), business):
            violations.append(f"{path.relative_to(PACKAGE)}:{violation}")
    assert violations == []


@pytest.mark.parametrize(
    "source,reason",
    [
        ("def run():\n def hidden(): pass", "local function or class"),
        ("def run():\n class Hidden: pass", "local function or class"),
        ("values = [item for group in groups for item in group]", "comprehension"),
        ("values = [\n item for item in items\n]", "comprehension"),
        ("def run():\n" + "    value = 1\n" * 26, "25 executable statements"),
        (
            "def run():\n    if first:\n        if second:\n            if third:\n"
            "                return None",
            "two indentation levels",
        ),
        (
            "def run(a,b,c,d,e,f,g,h,i,j,k,l,*extra,**options): pass",
            "13 parameters",
        ),
    ],
)
def test_structure_guard_detects_each_prohibited_shape(
    source: str, reason: str
) -> None:
    """Verify the guard on invalid code rather than only inspecting today's package.

    Args:
        source: Deliberately invalid project structure, never executed.
        reason: Required actionable diagnostic fragment.
    """
    violations = structure_violations(source, business=True)
    assert any(reason in violation for violation in violations)


def test_ordinary_methods_elif_and_single_line_comprehensions_are_allowed() -> None:
    """Keep ordinary Python classes and flat conditional chains readable."""
    source = """class Selection:
    def choose(self, values: list[int]) -> list[int]:
        if not values:
            return []
        elif len(values) == 1:
            return values
        return [value for value in values]
"""
    assert structure_violations(source, business=True) == []
