"""Check assertion strength against real policy defects without altering the repo."""

from pathlib import Path

import pytest

from tests.verification.mutations import MUTATIONS
from tests.verification.mutations import Mutation
from tests.verification.mutations import Trial
from tests.verification.mutations import copy_policy_checkout
from tests.verification.mutations import run_policy_tests


@pytest.fixture(scope="module")
def control(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Require unchanged policy assertions to pass before evaluating any mutants.

    Args:
        tmp_path_factory: Module-owned disposable checkout factory.

    Returns:
        Source-only control copy whose unchanged assertions pass.
    """
    checkout = tmp_path_factory.mktemp("policy-control")
    copy_policy_checkout(checkout)
    result = run_policy_tests(checkout)
    assert result.status == result.failures == result.errors == 0
    assert result.tests > 0
    return checkout


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[item.name for item in MUTATIONS])
def test_existing_policy_assertions_reject_deliberate_defects(
    mutation: Mutation, control: Path, tmp_path: Path
) -> None:
    """Demand genuine assertion failures from a syntactically valid changed rule.

    Args:
        mutation: Explicit threshold, credit, completeness or ordering defect.
        control: Verified unchanged source copy.
        tmp_path: Independent mutant checkout.
    """
    copy_policy_checkout(tmp_path, control)
    mutation.apply(tmp_path)
    result = run_policy_tests(tmp_path)
    assert result.killed, (mutation.name, result)


@pytest.mark.parametrize(
    "trial",
    [Trial(2, 0, 0, 1, 0), Trial(1, 1, 1, 1, 1), Trial(1, 1, 1, 0, 0)],
)
def test_invalid_execution_is_not_reported_as_a_killed_mutant(trial: Trial) -> None:
    """Collection/setup failures and non-assertion crashes cannot inflate evidence.

    Args:
        trial: Invalid execution with no usable assertion-strength evidence.
    """
    assert not trial.killed
