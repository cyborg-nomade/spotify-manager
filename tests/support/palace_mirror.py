"""Capture original saved-mirror paging, backups, exact bytes and audit behavior."""

import json
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.routines import analyse_library
from spotify_manager.routines import palace_of_memory as legacy
from tests.routines.test_palace_of_memory import saved_album
from tests.routines.test_palace_of_memory import spotify_saved_album
from tests.support.palace_run import FixedClock


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/palace_mirror.json"
PROFILES = (
    "missing",
    "unchanged",
    "changed",
    "invalid-old",
    "too-small",
    "invalid-page",
    "empty-next",
    "paged",
    "duplicate",
    "unusable",
    "publish-error",
    "read-error",
)


@dataclass
class MirrorReads:
    """Supply original scripted saved-album pages and publication observations.

    Args:
        profile: Original configured paging or publication boundary.
        trace: Original ordered observations.
    """

    profile: str
    trace: list[list[object]] = field(default_factory=list)

    def current_user_saved_albums(self, limit: int, offset: int) -> object:
        """Read original scripted live saved facts.

        Args:
            limit: Original configured page size.
            offset: Original raw-row offset.

        Returns:
            Original page shape and next-link authority.

        Raises:
            RuntimeError: The configured original read fails.
        """
        self.trace.append(["read", limit, offset])
        if self.profile == "read-error":
            raise RuntimeError("read failed")
        return _page(self.profile, offset)

    def publish(self, path: Path, *, source: str) -> bool:
        """Observe original publication after the local atomic replacement.

        Args:
            path: Original replaced canonical mirror location.
            source: Original publication source label.

        Returns:
            Original publication acknowledgment.

        Raises:
            OSError: The configured original publication fails.
        """
        self.trace.append(["publish", path.name, source])
        if self.profile == "publish-error":
            raise OSError("publish failed")
        return True

    def progress(self, message: str) -> None:
        """Observe original optional saved-mirror preflight messages.

        Args:
            message: Original visible stage.
        """
        self.trace.append(["progress", message])


def _page(profile: str, offset: int) -> object:
    if profile == "invalid-page":
        return {"items": None}
    if profile == "empty-next":
        return {"items": [], "next": "next"}
    size = 4 if profile == "too-small" else 6
    rows: list[object] = [spotify_saved_album(index) for index in range(size)]
    if profile == "duplicate":
        row = spotify_saved_album(0)
        album = cast(dict[str, object], row["album"])
        album["name"] = "Newest Album"
        rows.append(row)
    if profile == "unusable":
        rows.extend((None, {}, {"album": {}}, {"album": {"id": "invalid"}}))
    if profile == "paged":
        return {
            "items": rows[offset : offset + 3],
            "next": "next" if offset == 0 else None,
        }
    return {"items": rows, "next": None}


def _prepare(root: Path, profile: str) -> Path:
    path = root / "albums.json"
    if profile == "missing":
        return path
    if profile == "invalid-old":
        path.write_text("{invalid")
        return path
    size = 6 if profile == "unchanged" else 5
    path.write_text(
        json.dumps([saved_album(index) for index in range(size)], indent=2) + "\n"
    )
    return path


def _artifacts(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = path.read_text().replace(
                str(root), "ROOT"
            )
    return result


def _run(edge: MirrorReads, root: Path) -> object:
    path = _prepare(root, edge.profile)
    with ExitStack() as stack:
        stack.enter_context(patch.object(legacy, "datetime", FixedClock))
        stack.enter_context(
            patch.object(analyse_library, "publish_managed_path", edge.publish)
        )
        albums, refresh = legacy.refresh_saved_albums(
            cast(Spotify, edge),
            path=path,
            backups_dir=root / "backups",
            log_path=root / "audit.jsonl",
            progress_callback=edge.progress,
        )
    return {
        "albums": [album.model_dump() for album in albums],
        "refresh": asdict(refresh),
    }


def original_outcome(profile: str) -> object:
    """Observe original complete live preflight before extracting its coordinator.

    Args:
        profile: Original configured raw paging or publication behavior.

    Returns:
        Complete original result/error, trace and exact filesystem artifacts.
    """
    edge = MirrorReads(profile)
    outcome: dict[str, object] = {}
    with TemporaryDirectory() as location:
        root = Path(location)
        try:
            outcome["result"] = _run(edge, root)
        except RuntimeError as exc:
            outcome.update(error=type(exc).__name__, message=str(exc))
        outcome["trace"] = edge.trace
        outcome["artifacts"] = _artifacts(root)
        encoded = json.dumps(outcome, default=str).replace(str(root), "ROOT")
    return json.loads(encoded)


def cases() -> list[dict[str, object]]:
    """Read immutable original saved-mirror preflight observations.

    Returns:
        Original inputs and complete output/effect/byte evidence.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))
