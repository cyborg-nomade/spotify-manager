"""Observe legacy workflows against mutable files and ordered Spotify effects."""

import builtins
import copy
import io
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager import loaders_savers as files
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors import control_file_processors as control
from spotify_manager.processors import stats_processors as stats
from spotify_manager.processors import total_albums_processor as total
from spotify_manager.routines import convert_library_file as conversion
from spotify_manager.routines import count_items
from spotify_manager.routines import monthly_routine
from spotify_manager.utils import comparison
from tests.support.effects import FixedDatetime
from tests.support.effects import encode_value


@dataclass(frozen=True)
class Scenario:
    """Select original input and an optional effect interruption.

    Args:
        workflow: Original public operation.
        profile: Original boundary input.
        fault: Optional operation to interrupt.
        after: Whether the effect is accepted before interruption.
        occurrence: One-based selected invocation.
        repeats: Original reruns against already accepted authority.
    """

    workflow: str
    profile: str = "normal"
    fault: str = ""
    after: bool = False
    occurrence: int = 1
    repeats: int = 1


def scenarios() -> list[Scenario]:
    """Enumerate complete runs and partial acceptance boundaries.

    Returns:
        Stable original characterization cases.
    """
    result = []
    profiles = (
        "normal",
        "empty",
        "duplicates",
        "missing",
        "invalid",
        "retry",
        "saved-removal",
        "unsaved-addition",
        "present-all",
        "presenter-failure",
        "zero-limit",
    )
    for workflow in (
        "update",
        "incremental",
        "monthly",
        "convert",
        "analyse",
        "restore",
        "compare",
        "control",
        "stats",
        "count",
    ):
        for profile in profiles:
            result.append(Scenario(workflow, profile))
    for workflow in (
        "update",
        "incremental",
        "monthly",
        "convert",
        "restore",
        "control",
    ):
        for fault in (
            "saved",
            "next",
            "contains",
            "tracks",
            "create",
            "append",
            "save_albums",
            "save_control",
            "save_stats",
            "follow",
            "like",
        ):
            result.append(Scenario(workflow, fault=fault, after=False))
            result.append(Scenario(workflow, fault=fault, after=True))
    for repeats in (1, 2):
        profile = "monthly-additions"
        result.append(Scenario("monthly", profile, repeats=repeats))
        for fault in (
            "contains",
            "next",
            "tracks",
            "create",
            "append",
            "save_control",
            "save_albums",
            "save_stats",
        ):
            result.append(Scenario("monthly", profile, fault, False, repeats=repeats))
            result.append(Scenario("monthly", profile, fault, True, repeats=repeats))
    return result


def make_album(identifier: str) -> SimplifiedAlbum:
    """Build a sortable legacy album.

    Args:
        identifier: Original identity.

    Returns:
        Synthetic legacy file entry.
    """
    return SimplifiedAlbum(
        spotify_id=identifier,
        name=identifier.upper(),
        artist=SimplifiedArtist(spotify_id="artist", name="Artist"),
        ordering_string=identifier.upper(),
    )


def raw_album(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "name": identifier.upper(),
        "artists": [{"id": "artist", "name": "Artist"}],
    }


class Memory:
    """Record reads, accepted writes and native legacy outcomes.

    Args:
        scenario: Selected original inputs and interruption.
    """

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.events: list[object] = []
        self.counts: dict[str, int] = {}
        self.albums = [make_album("a"), make_album("b")]
        self.control = [
            ControlFileItem(album=self.albums[0], result="keep"),
            ControlFileItem(album=self.albums[1], result=""),
        ]
        self.export = YourLibraryFile.model_validate(
            {
                "albums": [
                    {"artist": "Artist", "album": "A", "uri": "spotify:album:a"}
                ],
                "artists": [{"name": "Artist", "uri": "spotify:artist:artist"}],
                "tracks": [
                    {
                        "artist": "Artist",
                        "album": "A",
                        "track": "Track",
                        "uri": "spotify:track:track",
                    }
                ],
            }
        )
        self.comparison: dict[str, Any] = {
            "remove": [{"id": "b"}],
            "add": [{"id": "c"}],
        }
        self.persisted: dict[str, object] = {}
        self.playlists: list[object] = []
        self._configure()

    def _configure(self) -> None:
        if self.scenario.profile == "monthly-additions":
            self.albums.extend([make_album("c"), make_album("d")])
        if self.scenario.profile == "empty":
            self.albums.clear()
            self.control.clear()
            self.comparison = {"remove": [], "add": []}
            self.export = YourLibraryFile(tracks=[], artists=[], albums=[])
        if self.scenario.profile == "duplicates":
            self.albums.append(make_album("a"))
            self.comparison["add"].append({"id": "c"})
        if self.scenario.profile == "missing":
            self.comparison["remove"] = [{"id": "unknown"}]
            self.control[0].album = make_album("unknown")
        if self.scenario.profile == "invalid":
            self.control[0].result = "unrecognized"
            self.comparison["add"] = [{"missing": "id"}]

    def begin(self, operation: str, value: object = None) -> None:
        """Observe an attempt before optional acceptance.

        Args:
            operation: Effect identity.
            value: Original complete arguments.

        Raises:
            RuntimeError: The configured pre-acceptance boundary is interrupted.
        """
        self.counts[operation] = self.counts.get(operation, 0) + 1
        self.events.append([operation, "before", copy.deepcopy(value)])
        if self._fails(operation, False):
            raise RuntimeError(f"interrupted {operation}")

    def end(self, operation: str, value: object = None) -> None:
        """Observe acceptance before the selected interruption.

        Args:
            operation: Effect identity.
            value: Original complete result.

        Raises:
            RuntimeError: The configured post-acceptance boundary is interrupted.
        """
        self.events.append([operation, "after", copy.deepcopy(value)])
        if self._fails(operation, True):
            raise RuntimeError(f"interrupted {operation}")

    def echo(self, *values: object) -> None:
        """Retain presentation and interrupt the first original page message.

        Args:
            values: Original positional print values.

        Raises:
            RuntimeError: The first selected page presentation is interrupted.
        """
        first = str(values[0]) if values else ""
        if (
            self.scenario.profile == "presenter-failure"
            and first.startswith("0/")
            and not self.counts.get("presenter")
        ):
            self.counts["presenter"] = 1
            raise RuntimeError("presentation failed")
        ORIGINAL_PRINT(*values)

    def _fails(self, operation: str, after: bool) -> bool:
        selected = self.scenario
        return (
            selected.fault == operation
            and selected.after == after
            and self.counts[operation] == selected.occurrence
        )

    def read_albums(self) -> list[SimplifiedAlbum]:
        """Return the original mutable legacy album authority."""
        self.begin("read_albums")
        self.end("read_albums", self.albums)
        return self.albums

    def read_control(self) -> list[ControlFileItem]:
        """Return the original mutable control authority."""
        self.begin("read_control")
        self.end("read_control", self.control)
        return self.control

    def read_export(self) -> YourLibraryFile:
        """Read the synthetic export authority."""
        self.begin("read_export")
        self.end("read_export", self.export)
        return self.export

    def read_comparison(self) -> dict[str, Any]:
        """Read an unchecked external comparison payload."""
        self.begin("read_comparison")
        self.end("read_comparison", self.comparison)
        return self.comparison

    def write(self, operation: str, value: object) -> None:
        """Accept file state at the original boundary.

        Args:
            operation: Original writer.
            value: Complete submitted state.
        """
        self.begin(operation, value)
        self.persisted[operation] = copy.deepcopy(value)
        self.end(operation, value)


class Catalog:
    """Supply permissive synthetic SDK responses and accepted mutation effects.

    Args:
        memory: Original observation authority.
    """

    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def current_user_saved_albums(self, *, limit: int, offset: int) -> dict[str, Any]:
        """Return a raw original saved-album page."""
        self.memory.begin("saved", [limit, offset])
        page: dict[str, Any] = {
            "total": 3,
            "offset": offset,
            "items": [{"album": raw_album("c")}, {}],
            "next": "albums",
        }
        if self.memory.counts["saved"] > 1 or self.memory.scenario.profile == "empty":
            page = {"total": 0, "offset": offset, "items": [], "next": None}
        if self.memory.scenario.profile == "invalid":
            page["items"].append({"unexpected": 1})
        self.memory.end("saved", page)
        return page

    def next(self, page: dict[str, Any]) -> dict[str, Any]:
        """Return the original next page or native recovery failure."""
        self.memory.begin("next", page)
        if self.memory.scenario.profile == "retry" and self.memory.counts["next"] == 1:
            raise RuntimeError("temporary")
        result = {
            "items": [{"album": raw_album("d")}],
            "total": 3,
            "offset": 2,
            "next": None,
        }
        if page["next"] == "tracks":
            result["items"] = [
                {"disc_number": "1", "track_number": "1", "uri": "first"}
            ]
        self.memory.end("next", result)
        return result

    def current_user_saved_albums_contains(self, ids: list[str]) -> list[bool]:
        """Observe original singleton membership queries."""
        self.memory.begin("contains", ids)
        result = [ids[0] not in ("b", "unknown")]
        if self.memory.scenario.profile == "saved-removal":
            result = [True]
        if self.memory.scenario.profile == "unsaved-addition":
            result = [False]
        self.memory.end("contains", result)
        return result

    def album(self, identifier: str) -> dict[str, object]:
        """Return original first-credit album metadata."""
        self.memory.begin("album", identifier)
        result = raw_album(identifier)
        self.memory.end("album", result)
        return result

    def album_tracks(self, identifier: str) -> dict[str, Any]:
        """Read ordered-track input with raw numeric coercion."""
        self.memory.begin("tracks", identifier)
        result = {
            "items": [{"disc_number": 2, "track_number": 1, "uri": "second"}, None],
            "next": "tracks",
        }
        self.memory.end("tracks", result)
        return result

    def user_playlist_create(self, user: str, *, name: str) -> dict[str, str]:
        """Accept an original named playlist creation."""
        self.memory.begin("create", [user, name])
        self.memory.playlists.append([user, name, []])
        self.memory.end("create", {"id": "playlist"})
        return {"id": "playlist"}

    def playlist_add_items(self, identifier: str, uris: list[str]) -> None:
        """Accept ordered track additions."""
        self.memory.begin("append", [identifier, uris])
        self.memory.playlists.append([identifier, copy.deepcopy(uris)])
        self.memory.end("append")

    def current_user_following_artists(self, ids: list[str]) -> list[bool]:
        """Read original follow membership."""
        self.memory.begin("following", ids)
        result = [self.memory.scenario.profile == "present-all"]
        self.memory.end("following", result)
        return result

    def current_user_saved_tracks_contains(self, ids: list[str]) -> list[bool]:
        """Read original liked-track membership."""
        self.memory.begin("liked", ids)
        result = [self.memory.scenario.profile == "present-all"]
        self.memory.end("liked", result)
        return result

    def user_follow_artists(self, ids: list[str]) -> None:
        """Accept original follow mutations."""
        self.memory.write("follow", ids)

    def current_user_saved_tracks_add(self, ids: list[str]) -> None:
        """Accept original liked-track mutations."""
        self.memory.write("like", ids)


def bind(monkeypatch: pytest.MonkeyPatch, memory: Memory) -> Catalog:
    """Redirect every legacy workflow's external effects.

    Args:
        monkeypatch: Scoped replacement owner.
        memory: Synthetic mutable authority.

    Returns:
        Original SDK boundary fake.
    """
    catalog = Catalog(memory)
    for module in (
        files,
        total,
        control,
        stats,
        conversion,
        monthly_routine,
        count_items,
    ):
        _bind_module(monkeypatch, module, memory)
    monkeypatch.setattr(total, "datetime", FixedDatetime)
    monkeypatch.setattr(builtins, "print", memory.echo)
    if memory.scenario.profile == "zero-limit":
        monkeypatch.setattr(total.settings, "limit", 0)
    monkeypatch.setattr(comparison, "get_spotipy_client", partial(identity, catalog))
    return catalog


def _bind_module(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, memory: Memory
) -> None:
    for name, callback in bindings(memory).items():
        if hasattr(module, name):
            monkeypatch.setattr(module, name, callback)


def identity[T](value: T) -> T:
    return value


def bindings(memory: Memory) -> dict[str, Callable[..., object]]:
    return {
        "load_total_albums_file": memory.read_albums,
        "load_control_file": memory.read_control,
        "load_your_library_file": memory.read_export,
        "load_comparison_file": memory.read_comparison,
        "save_total_albums_file": partial(memory.write, "save_albums"),
        "save_control_file": partial(memory.write, "save_control"),
        "save_stats_file": partial(memory.write, "save_stats"),
        "save_comparison_file": partial(memory.write, "save_comparison"),
    }


def public_run(scenario: Scenario, memory: Memory, catalog: Catalog) -> object:
    """Dispatch an original public workflow.

    Args:
        scenario: Selected workflow.
        memory: Legacy file authority.
        catalog: Synthetic SDK boundary.

    Returns:
        Original public result.
    """
    sp = cast(Spotify, catalog)
    if scenario.workflow in ("update", "incremental"):
        return total.update_total_album_list(sp, scenario.workflow == "incremental")
    if scenario.workflow == "monthly":
        monthly_routine.run_monthly_routines(sp)
        return None
    if scenario.workflow == "control":
        return control.check_album_results(sp, memory.control, memory.albums)
    if scenario.workflow == "stats":
        return stats.update_stats(memory.control, memory.albums)
    return other_public_run(scenario, sp)


def other_public_run(scenario: Scenario, sp: object) -> object:
    spotify = cast(Spotify, sp)
    if scenario.workflow == "convert":
        conversion.convert_your_library_file(spotify)
        return None
    if scenario.workflow == "analyse":
        conversion.analyse_comparison(spotify)
        return None
    if scenario.workflow == "restore":
        conversion.restore_your_library_from_file(spotify)
        return None
    if scenario.workflow == "compare":
        conversion.compare_your_library_and_all_albums()
        return None
    return count_items.count_artists_in_library()


def observe(
    scenario: Scenario,
    runner: Callable[[Scenario, Memory, Catalog], object] = public_run,
) -> object:
    """Capture output, effects and accepted state without outbound access.

    Args:
        scenario: Original profile and interruption.
        runner: Public or independently injected workflow.

    Returns:
        Immutable JSON-compatible original outcome.
    """
    memory = Memory(scenario)
    output = io.StringIO()
    with pytest.MonkeyPatch.context() as monkeypatch, redirect_stdout(output):
        catalog = bind(monkeypatch, memory)
        attempts = run_attempts(scenario, memory, catalog, runner, output)
    outcome = attempts[-1]
    if scenario.repeats > 1:
        return {"attempts": attempts}
    return outcome


def run_attempts(
    scenario: Scenario,
    memory: Memory,
    catalog: Catalog,
    runner: Callable[[Scenario, Memory, Catalog], object],
    output: io.StringIO,
) -> list[object]:
    results: list[object] = []
    for _ in range(scenario.repeats):
        result, error = run_attempt(scenario, memory, catalog, runner)
        state = [memory.albums, memory.control, memory.persisted, memory.playlists]
        results.append(
            encode_value(
                {
                    "output": output.getvalue(),
                    "events": memory.events,
                    "result": result,
                    "error": error,
                    "state": state,
                },
                Path("/tmp"),
            )
        )
    return results


def run_attempt(
    scenario: Scenario,
    memory: Memory,
    catalog: Catalog,
    runner: Callable[[Scenario, Memory, Catalog], object],
) -> tuple[object, object]:
    try:
        return runner(scenario, memory, catalog), None
    except (
        RuntimeError,
        IndexError,
        KeyError,
        ZeroDivisionError,
        TypeError,
        ValueError,
    ) as failure:
        return None, [type(failure).__name__, str(failure)]


ORIGINAL_PRINT = print
