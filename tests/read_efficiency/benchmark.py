"""Measure synthetic read overlap without credentials, real services or files."""

import argparse
import asyncio
import json
from dataclasses import asdict
from dataclasses import dataclass
from time import perf_counter

from spotify_manager.infrastructure.catalog_reads import AlbumCatalogReads
from spotify_manager.infrastructure.lookup_catalog import primary_tracks
from tests.read_efficiency.catalog_memory import CatalogPages
from tests.read_efficiency.catalog_memory import release_ids


@dataclass(frozen=True)
class ReadMeasurement:
    """Report one read budget and its illustrative local duration.

    Args:
        seconds: Observed elapsed duration, never a correctness threshold.
        requests: Concrete metadata requests issued.
        peak_reads: Peak simultaneous metadata reads.
        result_ids: Number of unique primary-credit track IDs returned.
    """

    seconds: float
    requests: int
    peak_reads: int
    result_ids: int


@dataclass(frozen=True)
class CatalogBenchmark:
    """Compare identical fixed inputs before and after the native optimization.

    Args:
        sequential: Original ordered implementation's measurements.
        optimized: Bounded native implementation's measurements.
        same_results: Whether both complete ordered result lists are identical.
    """

    sequential: ReadMeasurement
    optimized: ReadMeasurement
    same_results: bool


async def benchmark(count: int, repetitions: int, latency: float) -> CatalogBenchmark:
    """Measure controlled metadata I/O while keeping decisions and results fixed.

    Args:
        count: Number of distinct synthetic album identities.
        repetitions: Number of complete repeated catalogs in this observation.
        latency: Simulated seconds spent inside each independent read.

    Returns:
        Exact request/overlap counts and illustrative elapsed durations.

    Raises:
        ValueError: Counts or simulated latency are negative.
    """
    if count < 0 or repetitions < 0 or latency < 0:
        raise ValueError("Counts and simulated latency must be nonnegative.")
    identifiers = release_ids(count) * repetitions
    serial, concurrent = CatalogPages(latency=latency), CatalogPages(latency=latency)
    started = perf_counter()
    expected = await primary_tracks(serial, "artist", identifiers, 20)
    original = _measurement(serial, started, expected)
    started = perf_counter()
    actual = await AlbumCatalogReads(concurrent).primary_tracks(
        "artist", identifiers, 20
    )
    optimized = _measurement(concurrent, started, actual)
    return CatalogBenchmark(original, optimized, expected == actual)


def _measurement(
    source: CatalogPages, started: float, result: list[str]
) -> ReadMeasurement:
    return ReadMeasurement(
        round(perf_counter() - started, 6), len(source.calls), source.peak, len(result)
    )


def main() -> None:
    """Print the offline benchmark; elapsed time is not a live-service speedup claim."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--latency", type=float, default=0.025)
    arguments = parser.parse_args()
    result = asyncio.run(
        benchmark(arguments.count, arguments.repeat, arguments.latency)
    )
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
