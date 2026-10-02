"""Compare library analysis with complete frozen original runs and resumptions."""

from typing import Literal
from typing import cast

import pytest

from tests.support import library_analysis_run as original
from tests.support.effects import Fault


@pytest.mark.parametrize("case", original.cases())
def test_public_analysis_preserves_original_effects(case: dict[str, object]) -> None:
    """Preserve accepted file bytes, progress, retries and recovery prefixes.

    Args:
        case: Immutable original complete invocation and observation.
    """
    fault = cast(dict[str, object] | None, case["fault"])
    assert (
        original.outcome(
            cast(str, case["kind"]),
            cast(str, case["profile"]),
            cast(bool, case["full"]),
            None
            if fault is None
            else Fault(
                cast(str, fault["operation"]),
                cast(Literal["before", "after"], fault["phase"]),
                cast(int, fault["occurrence"]),
            ),
            cast(bool, case["resume"]),
        )
        == case["outcome"]
    )
