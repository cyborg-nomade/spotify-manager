"""Measure read-only explorer builds and warm serialization without live music calls."""

import argparse
import json
import math
import resource
import sys
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv

from spotify_manager.application.listening import get_listening_activity
from spotify_manager.application.listening import get_listening_comparison
from spotify_manager.application.listening import get_listening_discoveries
from spotify_manager.application.listening import get_listening_evolution
from spotify_manager.application.listening import get_listening_overview
from spotify_manager.application.listening import get_listening_rankings
from spotify_manager.application.listening import get_listening_rediscovery
from spotify_manager.bootstrap.library_data import get_library_data_service
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import payload_sha256
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RediscoveryOptions
from spotify_manager.infrastructure.listening.build import build_listening_index
from spotify_manager.infrastructure.listening.reader import ListeningIndex
from spotify_manager.infrastructure.scrobble_downloads import ScrobbleHistoryFiles


@dataclass
class Measurements:
    """Measure explicit named calls and JSON serialization in their execution order."""

    previous: float = field(default_factory=time.perf_counter)
    milliseconds: dict[str, float] = field(default_factory=dict)
    bytes: dict[str, int] = field(default_factory=dict)

    def mark(self, name: str, payload: object) -> None:
        """Include serialization time and record response size after one direct call.

        Args:
            name: Analytical operation name.
            payload: Already evaluated dataclass, never an executable dependency.
        """
        # The standard JSON encoder requires a fallback for dataclass date values.
        encoded = json.dumps(payload, separators=(",", ":"), default=str).encode()
        now = time.perf_counter()
        self.milliseconds[name] = round((now - self.previous) * 1000, 3)
        self.bytes[name] = len(encoded)
        self.previous = time.perf_counter()


def _core(index: ListeningIndex, query: ListeningQuery) -> Measurements:
    measurements = Measurements()
    measurements.mark("overview", asdict(get_listening_overview(index, query)))
    measurements.mark("activity", asdict(get_listening_activity(index, query)))
    measurements.mark(
        "rankings", asdict(get_listening_rankings(index, query, RankingOptions()))
    )
    measurements.mark("evolution", asdict(get_listening_evolution(index, query)))
    return measurements


def _insights(index: ListeningIndex, query: ListeningQuery) -> Measurements:
    measurements = Measurements()
    measurements.mark("discovery", asdict(get_listening_discoveries(index, query)))
    measurements.mark(
        "rediscovery",
        asdict(get_listening_rediscovery(index, query, RediscoveryOptions())),
    )
    measurements.mark("comparison", asdict(get_listening_comparison(index, query)))
    return measurements


def _warm(index: ListeningIndex, query: ListeningQuery) -> dict[str, float]:
    samples: dict[str, list[float]] = {}
    for _attempt in range(10):
        measurement = _core(index, query)
        for name, duration in measurement.milliseconds.items():
            samples.setdefault(name, []).append(duration)
    results = {}
    for name, durations in samples.items():
        results[name] = sorted(durations)[math.ceil(len(durations) * 0.95) - 1]
    return results


def _synthetic(path: Path, count: int) -> ArtifactMetadata:
    first = int(datetime(2007, 11, 27, tzinfo=UTC).timestamp() * 1000)
    with path.open("w") as stream:
        stream.write('{"username":"synthetic","scrobbles":[')
        for index in range(count):
            row = {
                "date": first + index * 600000,
                "artist": f"Artist {index % 15000}",
                "track": f"Track {index % 120000}",
                "album": f"Album {index % 40000}",
                "albumId": "",
            }
            stream.write("," if index else "")
            stream.write(json.dumps(row, separators=(",", ":")))
        stream.write("]}")
    return _local_metadata(path)


def _local_metadata(path: Path) -> ArtifactMetadata:
    content = path.read_bytes()
    return ArtifactMetadata(
        path.name,
        "artifacts/history",
        payload_sha256(content),
        len(content),
        datetime.now(UTC).isoformat(),
        "benchmark",
    )


def _measure(source: Path, metadata: ArtifactMetadata, root: Path) -> dict[str, object]:
    path = root / "index.sqlite"
    started = time.perf_counter()
    built = build_listening_index(source, path, metadata)
    build_seconds = time.perf_counter() - started
    index = ListeningIndex(path, built)
    first = (
        local_instant(built.first_ms, "Europe/Berlin").date()
        if built.first_ms is not None
        else date(2024, 1, 1)
    )
    last = (
        local_instant(built.last_ms, "Europe/Berlin").date()
        if built.last_ms is not None
        else first
    )
    query = ListeningQuery(first, last)
    cold = _core(index, query)
    insights = _insights(index, query)
    warm = _warm(index, query)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "rows": built.scrobbles,
        "source_bytes": built.source_bytes,
        "source_sha256": built.source_sha256,
        "published_at": built.published_at,
        "first_date": str(first),
        "last_date": str(last),
        "build_seconds": round(build_seconds, 3),
        "cold_ms_including_first_timezone_build": cold.milliseconds,
        "warm_p95_ms_including_serialization": warm,
        "response_bytes": cold.bytes,
        "insight_cold_ms": insights.milliseconds,
        "peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
        "index_bytes": sum(item.stat().st_size for item in root.glob("index.*")),
    }


def run(arguments: argparse.Namespace) -> dict[str, object]:
    """Own all temporary source/index files and optionally read a real publication.

    Args:
        arguments: Parsed explicit source mode and output selection.

    Returns:
        Aggregate timings and resource usage without listening names or credentials.
    """
    with TemporaryDirectory(prefix="listening-benchmark-") as directory:
        root = Path(directory)
        if arguments.published:
            return _published(root)
        source = arguments.source or root / "synthetic.json"
        metadata = (
            _synthetic(source, arguments.synthetic)
            if arguments.synthetic
            else _local_metadata(source)
        )
        return _measure(source, metadata, root)


def _published(root: Path) -> dict[str, object]:
    snapshot = ScrobbleHistoryFiles(get_library_data_service(), root).prepare()
    if snapshot is None:
        raise ValueError("No scrobble artifact is published.")
    try:
        return _measure(snapshot.path, snapshot.metadata, root)
    finally:
        snapshot.close()


def main() -> None:
    """Parse an explicit read-only benchmark mode and write its aggregate report."""
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--published", action="store_true")
    sources.add_argument("--source", type=Path)
    sources.add_argument("--synthetic", type=int)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = run(arguments)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
