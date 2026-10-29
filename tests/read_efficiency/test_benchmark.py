"""Keep measured request budgets independent of noisy wall-clock assertions."""

import pytest

from tests.read_efficiency.benchmark import benchmark


async def test_benchmark_compares_equal_results_and_exact_read_budgets() -> None:
    """Check counts and overlap while leaving elapsed durations illustrative."""
    result = await benchmark(80, 2, 0)
    assert result.same_results
    assert (result.sequential.requests, result.sequential.peak_reads) == (8, 1)
    assert (result.optimized.requests, result.optimized.peak_reads) == (4, 4)
    assert result.sequential.result_ids == result.optimized.result_ids == 80


@pytest.mark.parametrize(
    "count, repeats, latency", [(-1, 1, 0), (1, -1, 0), (1, 1, -1)]
)
async def test_benchmark_rejects_invalid_synthetic_inputs(
    count: int, repeats: int, latency: float
) -> None:
    """Reject invalid measurements before any read or elapsed-time observation.

    Args:
        count: Synthetic identity count.
        repeats: Complete catalog repetitions.
        latency: Synthetic I/O delay.
    """
    with pytest.raises(ValueError, match="nonnegative"):
        await benchmark(count, repeats, latency)
