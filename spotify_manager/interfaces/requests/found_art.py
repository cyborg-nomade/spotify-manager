"""Cohesive file locations for recommendation execution."""

from dataclasses import dataclass
from pathlib import Path


FILES_DIR = Path(__file__).resolve().parents[2] / "files"


@dataclass(frozen=True)
class FoundArtResources:
    """Identify canonical history, the legacy delta, cache and accepted audit.

    Args:
        export_path: Canonical Last.fm history file.
        recent_path: Legacy history delta location.
        cache_path: Recommendation cache location.
        log_path: Accepted recommendation audit.
    """

    export_path: Path = FILES_DIR / "lastfmstats-man-et-arms.json"
    recent_path: Path = FILES_DIR / "found_art_recent_scrobbles.jsonl"
    cache_path: Path = FILES_DIR / "found_art_cache.json"
    log_path: Path = FILES_DIR / "found_art_log.jsonl"
