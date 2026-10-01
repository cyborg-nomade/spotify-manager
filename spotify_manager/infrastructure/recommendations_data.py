"""Original recommendation cache and append-only audit codecs and filesystem IO."""

import json
from collections.abc import Callable
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import cast

from spotify_manager.application.found_art_values import FoundArtStateError
from spotify_manager.application.found_art_values import FoundArtSummary
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_matching import FoundArtResult
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


def load_cache(path: Path) -> dict[str, object]:
    """Read the original cache without silently replacing corruption.

    Args:
        path: Original neighborhood cache source.

    Returns:
        Original validated payload, or an empty version-one cache when absent.

    Raises:
        FoundArtStateError: Existing bytes cannot be read or fail the original schema.
    """
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FoundArtStateError(f"Found Art cache is invalid: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise FoundArtStateError(f"Found Art cache is invalid: {path}")
    if not isinstance(payload.get("entries"), dict):
        raise FoundArtStateError(f"Found Art cache is invalid: {path}")
    return cast(dict[str, object], payload)


def save_cache(payload: dict[str, object], path: Path) -> None:
    """Atomically checkpoint original cache bytes after one completed neighborhood.

    Args:
        payload: Original mutable cache representation.
        path: Original cache destination.

    Raises:
        FoundArtStateError: Directory creation, temporary write or replacement fails.
        TypeError: A caller supplies non-JSON values, retaining original propagation.
    """
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise FoundArtStateError(f"Could not save Found Art cache: {path}") from exc


def _fetched_at(
    entry: dict[str, object], parse_timestamp: Callable[[str], datetime]
) -> datetime:
    stamp = parse_timestamp(str(entry["fetched_at"]))
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def _neighbor(raw: dict[str, object]) -> LastFmSimilarTrack:
    return LastFmSimilarTrack(
        str(raw["artist"]),
        str(raw["track"]),
        float(cast(float | str, raw["match"])),
    )


def _neighbors(raw: object) -> tuple[LastFmSimilarTrack, ...] | None:
    if not isinstance(raw, list):
        return None
    tracks = []
    for item in raw:
        if isinstance(item, dict):
            tracks.append(_neighbor(item))
    return tuple(tracks)


def cached_neighbors(
    entry: object,
    week: date,
    listening_week: Callable[[datetime], date],
    parse_timestamp: Callable[[str], datetime] = datetime.fromisoformat,
) -> tuple[LastFmSimilarTrack, ...] | None:
    """Decode original current-week entries with permissive row coercion.

    Args:
        entry: Original raw cache entry.
        week: Effective listening week.
        listening_week: Original timezone-aware calendar boundary.
        parse_timestamp: Original ISO constructor, preserving injected clock types.

    Returns:
        Ordered decoded neighbors, including empty hits, or a complete cache miss.

    Raises:
        OverflowError: Original numeric conversion exceeds float limits.
    """
    if not isinstance(entry, dict):
        return None
    try:
        if listening_week(_fetched_at(entry, parse_timestamp)) != week:
            return None
        return _neighbors(entry["tracks"])
    except KeyError, TypeError, ValueError:
        return None


def _added_keys(
    record: object, key_of: Callable[[str, str], TrackKey]
) -> set[TrackKey]:
    results = record.get("results") if isinstance(record, dict) else None
    if not isinstance(results, list):
        raise ValueError("results must be a list")
    keys = set()
    for result in results:
        if not isinstance(result, dict) or result.get("action") != "added":
            continue
        candidate = result.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        keys.add(key_of(str(candidate["artist"]), str(candidate["track"])))
    return keys


def _update_keys(
    keys: set[TrackKey], line: str, key_of: Callable[[str, str], TrackKey]
) -> None:
    if not line.strip():
        return
    keys.update(_added_keys(json.loads(line), key_of))


def previously_added_keys(
    path: Path, key_of: Callable[[str, str], TrackKey]
) -> set[TrackKey]:
    """Read actually added identities with original physical-line error diagnostics.

    Args:
        path: Original audit source.
        key_of: Original edition-tolerant identity boundary.

    Returns:
        Normalized added identities, or an empty set when the log is absent.

    Raises:
        FoundArtStateError: Reading or parsing fails at the last observed physical line.
    """
    if not path.exists():
        return set()
    keys: set[TrackKey] = set()
    current_line = 0
    try:
        with path.open(encoding="utf-8") as log_file:
            for line_number, line in enumerate(log_file, start=1):
                current_line = line_number
                _update_keys(keys, line, key_of)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        detail = f" at line {current_line}" if current_line else ""
        raise FoundArtStateError(
            f"Found Art audit log is invalid{detail}: {path}"
        ) from exc
    return keys


def _candidate_record(candidate: FoundArtCandidate) -> dict[str, object]:
    return {
        "artist": candidate.artist,
        "track": candidate.track,
        "score": candidate.score,
        "best_match": candidate.best_match,
        "supporting_seeds": list(candidate.supporting_seeds),
        "base_rank": candidate.base_rank,
        "weekly_rank": candidate.weekly_rank,
    }


def _match_record(match: SpotifyTrackMatch | None) -> dict[str, object] | None:
    if match is None:
        return None
    return {
        "spotify_id": match.spotify_id,
        "uri": match.uri,
        "track": match.track,
        "artists": list(match.artists),
        "album": match.album,
        "track_similarity": match.track_similarity,
        "popularity": match.popularity,
    }


def result_record(result: FoundArtResult) -> dict[str, object]:
    """Serialize one original result without adding internal matching fields.

    Args:
        result: Original recommendation and Spotify outcome.

    Returns:
        Original JSON-compatible candidate, optional match and action fields.
    """
    return {
        "candidate": _candidate_record(result.candidate),
        "match": _match_record(result.match),
        "action": result.action,
    }


def _seed_record(seed: FoundArtSeed) -> dict[str, object]:
    return {
        "artist": seed.artist,
        "track": seed.track,
        "source": seed.source,
        "play_count": seed.play_count,
        "source_play_count": seed.source_play_count,
        "weight": seed.weight,
        "weekly_rank": seed.weekly_rank,
    }


def _summary_record(summary: FoundArtSummary) -> dict[str, object]:
    return {
        "generated_at": summary.generated_at.isoformat(),
        "week_start": summary.week_start.isoformat(),
        "playlist_id": summary.playlist_id,
        "requested_count": summary.requested_count,
        "seed_count": summary.seed_count,
        "history_tracks": summary.history_tracks,
        "history_scrobbles": summary.history_scrobbles,
        "live_scrobbles_added": summary.live_scrobbles_added,
        "candidate_count": summary.candidate_count,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "dry_run": summary.dry_run,
        "seeds": [_seed_record(seed) for seed in summary.seeds],
        "results": [result_record(result) for result in summary.results],
    }


def append_audit(summary: FoundArtSummary, path: Path) -> None:
    """Append original audit bytes after accepted effects, including previews.

    Args:
        summary: Completed original recommendation run.
        path: Original audit destination.

    Raises:
        FoundArtStateError: Directory creation or log append fails.
    """
    record = _summary_record(summary)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise FoundArtStateError(f"Could not write Found Art log: {path}") from exc
