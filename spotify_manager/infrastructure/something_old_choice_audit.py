"""Recover usable completed selections from available legacy JSON Lines audits."""

import json
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter
from pydantic import ValidationError

from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.infrastructure.something_old_choice_schema import validate_choice


_CHOICE = TypeAdapter(ArtistChoice)


def _track_ids(raw: object) -> list[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    result = []
    for track in raw:
        if not isinstance(track, dict) or not isinstance(track.get("spotify_id"), str):
            return None
        result.append(track["spotify_id"])
    return result


def _audit_choice(raw: object) -> ArtistChoice | None:
    if not isinstance(raw, dict) or raw.get("action") != "added":
        return None
    if raw.get("dry_run") is True or raw.get("playlist_length_before") != 0:
        return None
    mapped, artist = raw.get("spotify_artist"), raw.get("artist")
    if not isinstance(mapped, dict) or not isinstance(artist, dict):
        return None
    tracks = _track_ids(raw.get("tracks"))
    if tracks is None or raw.get("playlist_length_after") != len(tracks):
        return None
    release = raw.get("release")
    record = {
        "artist_id": mapped.get("spotify_id"),
        "artist_name": mapped.get("name"),
        "lastfm_artist": artist.get("artist"),
        "mode": raw.get("mode"),
        "chosen_at": raw.get("generated_at"),
        "playlist_id": raw.get("playlist_id"),
        "track_ids": tracks,
        "provenance": "audit",
        "release_name": release.get("name") if isinstance(release, dict) else None,
        "release_id": release.get("spotify_id") if isinstance(release, dict) else None,
    }
    return _validated_choice(record)


def _validated_choice(raw: dict[str, object]) -> ArtistChoice | None:
    try:
        choice = _CHOICE.validate_python(raw)
        validate_choice(choice)
    except ValidationError, StateDocumentError:
        return None
    return choice


def _line_choice(line: str) -> ArtistChoice | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    return _audit_choice(raw)


def _read_lines(source: TextIO) -> tuple[ArtistChoice, ...]:
    result = []
    for line in source:
        choice = _line_choice(line)
        if choice is not None:
            result.append(choice)
    return tuple(result)


def read_choice_audit(path: Path) -> tuple[ArtistChoice, ...]:
    """Import complete applied records with explicit Spotify identities and dates.

    Args:
        path: Available legacy selection audit.

    Returns:
        Usable recorded selections, tagged as audit imports; missing files are empty.

    Raises:
        SomethingOldError: An existing audit cannot be read.
    """
    try:
        with path.open(encoding="utf-8") as source:
            return _read_lines(source)
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeError) as exc:
        raise SomethingOldError(
            f"Could not read Something Old choice audit: {path}"
        ) from exc
