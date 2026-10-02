"""Observe original JSON bytes, output and partial file acceptance."""

import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import cast

import pytest

from spotify_manager import loaders_savers
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import StatsFileItem
from tests.loaders_savers.test_loaders import library_album
from tests.loaders_savers.test_loaders import library_artist
from tests.loaders_savers.test_loaders import library_track
from tests.loaders_savers.test_loaders import simplified_album
from tests.loaders_savers.test_loaders import stats_report
from tests.support.effects import encode_value


@dataclass(frozen=True)
class FileScenario:
    """Select an original persistence operation and failure boundary.

    Args:
        operation: Original public reader or writer.
        profile: Original raw input or selected failure.
    """

    operation: str
    profile: str


PATHS = {
    "album_tracks_cache": "ALBUM_TRACKS_CACHE_PATH",
    "control_file": "CONTROL_FILE_PATH",
    "total_albums_file": "TOTAL_ALBUMS_PATH",
    "total_albums_new_file": "TOTAL_ALBUMS_NEW_PATH",
    "your_library_file": "YOUR_LIBRARY_PATH",
    "comparison_file": "COMPARISON_PATH",
    "total_artists_file": "TOTAL_ARTISTS_PATH",
    "stats_history_file": "STATS_HISTORY_PATH",
    "stats_history": "STATS_HISTORY_PATH",
    "stats_file": "STATS_FILE_PATH",
}


def file_scenarios() -> list[FileScenario]:
    """Enumerate original readers, writers and partial file failures.

    Returns:
        Stable original persistence observations.
    """
    result = []
    for name in PATHS:
        if name in ("stats_history", "stats_file"):
            continue
        for profile in (
            "normal",
            "missing",
            "invalid",
            "null",
            "scalar",
            "empty",
            "bad-model",
        ):
            result.append(FileScenario("load_" + name, profile))
    for name in PATHS:
        if name in ("your_library_file", "stats_history_file"):
            continue
        for profile in (
            "normal",
            "serialize",
            "replace-before",
            "replace-after",
            "publish-before",
            "publish-after",
            "missing-parent",
        ):
            result.append(FileScenario("save_" + name, profile))
    return result


def inputs() -> dict[str, object]:
    """Build typed synthetic inputs without touching operator files.

    Returns:
        Original payload families.
    """
    album = simplified_album()
    return {
        "album_tracks_cache": {"album": [{"id": "track", "name": "Élan"}]},
        "control_file": [ControlFileItem(album=album, result="")],
        "total_albums_file": [album],
        "total_albums_new_file": [library_album()],
        "your_library_file": {
            "tracks": [library_track().model_dump()],
            "albums": [library_album().model_dump()],
            "artists": [library_artist().model_dump()],
        },
        "comparison_file": {"add": [{"name": "Élan", "id": "album"}], "remove": []},
        "total_artists_file": [library_artist()],
        "stats_history_file": {"period": stats_report()},
        "stats_history": {"period": stats_report()},
        "stats_file": StatsFileItem(
            total_saved_albums=2,
            total_listened_albums=1,
            pct_listened_albums=0.5,
            total_removed_albums=0,
            pct_removed_albums=0.0,
            total_kept_albums=1,
            pct_kept_albums=1.0,
            last_listened_to_index=0,
        ),
    }


def failed_serialization(value: object) -> object:
    raise ValueError("serialization failed")


class FileEffects:
    """Observe accepted replacement and publication independently.

    Args:
        scenario: Original failure boundary.
    """

    def __init__(self, scenario: FileScenario) -> None:
        self.scenario = scenario
        self.events: list[object] = []

    def replace(self, path: Path, target: Path | str) -> Path:
        """Retain accepted replacement bytes before an optional failure.

        Args:
            path: Original temporary path.
            target: Original destination.

        Returns:
            Original accepted destination.

        Raises:
            OSError: The selected replacement boundary is interrupted.
        """
        self.events.append(["replace", path.name, Path(target).name])
        if self.scenario.profile == "replace-before":
            raise OSError("replacement failed")
        result = ORIGINAL_REPLACE(path, target)
        if self.scenario.profile == "replace-after":
            raise OSError("replacement failed")
        return result

    def publish(self, path: Path, *, source: str) -> None:
        """Retain original accepted publication order.

        Args:
            path: Original accepted path.
            source: Original publication label.

        Raises:
            OSError: The selected publication boundary is interrupted.
        """
        self.events.append(["publish", "before", path.name, source])
        if self.scenario.profile == "publish-before":
            raise OSError("publication failed")
        self.events.append(["publish", "after", path.read_text()])
        if self.scenario.profile == "publish-after":
            raise OSError("publication failed")


ORIGINAL_REPLACE = Path.replace
ACTIVE_EFFECTS: FileEffects | None = None


def replace_observed(path: Path, target: Path | str) -> Path:
    assert ACTIVE_EFFECTS is not None
    return ACTIVE_EFFECTS.replace(path, target)


def seed(path: Path, profile: str, value: object) -> None:
    if profile == "missing-parent":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if profile in ("missing", "missing-parent"):
        return
    payload = encode_value(value, path.parent)
    text = json.dumps(payload, ensure_ascii=False)
    overrides = {
        "invalid": "{",
        "null": "null",
        "scalar": '"unexpected"',
        "empty": "[]",
        "bad-model": '[{"bad": 1}]',
    }
    path.write_text(overrides.get(profile, text))


def observe_file(scenario: FileScenario, module: ModuleType = loaders_savers) -> object:
    """Capture original bytes and errors after one complete file operation.

    Args:
        scenario: Original input and failure.
        module: Original capture module or current compatibility facade.

    Returns:
        Immutable original storage outcome.
    """
    with TemporaryDirectory() as folder:
        return observe_in_folder(scenario, module, Path(folder))


def observe_in_folder(scenario: FileScenario, module: ModuleType, root: Path) -> object:
    name = scenario.operation.removeprefix("load_").removeprefix("save_")
    path = root / "value.json"
    if scenario.profile == "missing-parent":
        path = root / "missing" / "value.json"
    value = inputs()[name]
    seed(path, scenario.profile, value)
    effects = FileEffects(scenario)
    output = io.StringIO()
    with pytest.MonkeyPatch.context() as patch, redirect_stdout(output):
        patch.setattr(module, PATHS[name], path)
        patch.setattr(module, "publish_managed_path", effects.publish)
        patch.setattr(sys.modules[__name__], "ACTIVE_EFFECTS", effects)
        patch.setattr(Path, "replace", replace_observed)
        if scenario.profile == "serialize":
            patch.setattr(module, "serialize_model_list", failed_serialization)
        outcome = invoke_file(module, scenario.operation, value)
    files = {}
    for item in sorted(root.rglob("*")):
        if item.is_file():
            files[str(item.relative_to(root))] = item.read_text()
    return encode_value(
        {
            "outcome": outcome,
            "output": output.getvalue(),
            "effects": effects.events,
            "files": files,
        },
        root,
    )


def invoke_file(module: ModuleType, operation: str, value: object) -> object:
    function = cast(Callable[..., object], getattr(module, operation))
    try:
        result = function(value) if operation.startswith("save_") else function()
        return ["result", result]
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return ["error", type(error).__name__, str(error)]
