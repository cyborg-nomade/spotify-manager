"""Original append-only Sauvignon audit serialization and accepted-history parsing."""

import json
from dataclasses import asdict
from pathlib import Path

from spotify_manager.application.sauvignon_values import SauvignonStateError
from spotify_manager.application.sauvignon_values import SauvignonSummary
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import canonical_album_key
from spotify_manager.domain.album_selection import SauvignonResult


def _added_keys(record: object) -> set[AlbumKey]:
    raw_results = record.get("results") if isinstance(record, dict) else None
    if not isinstance(raw_results, list):
        raise ValueError("results must be a list")
    keys = set()
    for result in raw_results:
        key = _added_key(result)
        if key is not None:
            keys.add(key)
    return keys


def _added_key(result: object) -> AlbumKey | None:
    if not isinstance(result, dict) or result.get("action") != "added":
        return None
    album = result.get("album")
    if not isinstance(album, dict):
        raise ValueError("album must be an object")
    return canonical_album_key(str(album["artist"]), str(album["album"]))


def previously_added_album_keys(path: Path) -> set[AlbumKey]:
    """Read original actual additions with physical-line diagnostics.

    Args:
        path: Original audit location.

    Returns:
        Distinct normalized accepted album identities.

    Raises:
        SauvignonStateError: The original audit cannot be read or decoded.
    """
    if not path.exists():
        return set()
    keys: set[AlbumKey] = set()
    position = [0]
    try:
        _read_keys(path, keys, position)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        detail = f" at line {position[0]}" if position[0] else ""
        raise SauvignonStateError(
            f"Sauvignon audit log is invalid{detail}: {path}"
        ) from exc
    return keys


def _line_keys(line: str) -> set[AlbumKey]:
    if not line.strip():
        return set()
    return _added_keys(json.loads(line))


def _read_keys(path: Path, keys: set[AlbumKey], position: list[int]) -> None:
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            position[0] = line_number
            keys.update(_line_keys(line))


def _recommendation_record(item: AlbumRecommendation) -> dict[str, object]:
    return {
        "artist": item.artist,
        "album": item.album,
        "score": item.score,
        "best_match": item.best_match,
        "supporting_tracks": list(item.supporting_tracks),
        "base_rank": item.base_rank,
        "weekly_rank": item.weekly_rank,
    }


def _result_record(result: SauvignonResult) -> dict[str, object]:
    return {
        "recommendation": _recommendation_record(result.recommendation),
        "album": asdict(result.album) if result.album is not None else None,
        "first_track": (
            asdict(result.first_track) if result.first_track is not None else None
        ),
        "action": result.action,
    }


def append_log(summary: SauvignonSummary, path: Path) -> None:
    """Append one complete recommendation run using original bytes.

    Args:
        summary: Original completed outcome.
        path: Original audit destination.

    Raises:
        SauvignonStateError: The original destination cannot be written.
    """
    record = {
        "generated_at": summary.generated_at.isoformat(),
        "week_start": summary.week_start.isoformat(),
        "playlist_id": summary.playlist_id,
        "requested_count": summary.requested_count,
        "history_albums": summary.history_albums,
        "history_scrobbles": summary.history_scrobbles,
        "live_scrobbles_added": summary.live_scrobbles_added,
        "seed_count": summary.seed_count,
        "track_candidate_count": summary.track_candidate_count,
        "album_candidate_count": summary.album_candidate_count,
        "playlist_length_before": summary.playlist_length_before,
        "playlist_length_after": summary.playlist_length_after,
        "paused": summary.paused,
        "dry_run": summary.dry_run,
        "results": [_result_record(result) for result in summary.results],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise SauvignonStateError(f"Could not write Sauvignon log: {path}") from exc
