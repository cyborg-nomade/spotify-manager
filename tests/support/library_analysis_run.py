"""Freeze original export/live library runs, file bytes and restart effect prefixes."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.routines import analyse_library as legacy
from tests.routines import test_analyse_library as fake
from tests.support.effects import Fault
from tests.support.effects import Json
from tests.support.effects import Trace
from tests.support.effects import encode_value


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/library_analysis_run.json"
)
KINDS = ("export", "sync", "mirrors", "albums", "tracks", "artists")
PROFILES = (
    "normal",
    "empty",
    "duplicates",
    "additions",
    "server-retry",
    "artist-fallback",
    "cancel",
    "cancel-wait",
    "no-export",
    "no-progress",
)


@dataclass
class AnalysisObservations:
    """Observe original prompts, progress, cancellation and live fake authority.

    Args:
        profile: Original configured read or interruption scenario.
        root: Original isolated output family.
        trace: Complete original accepted effect observations.
        spotify: Original live fake authority.
        cancel_calls: Original cancellation observation count.
        run_calls: Original fresh-run clock observation count.
    """

    profile: str
    root: Path
    trace: Trace
    spotify: fake.FakeSpotify
    cancel_calls: int = 0
    run_calls: int = 0

    def run_id(self) -> str:
        """Supply distinct original sortable identities for fresh completed runs.

        Returns:
            Original deterministic next fresh invocation identity.
        """
        self.run_calls += 1
        identity = f"original-run-{self.run_calls}"
        self.trace.record("run-id", "clock", identity)
        return identity

    def echo(self, value: str) -> None:
        """Observe original visible planning and retry output.

        Args:
            value: Original complete message.
        """
        self.trace.record("echo", "message", value)

    def progress(
        self, resource: legacy.ResourceName, done: int, total: int | None, label: str
    ) -> None:
        """Observe original resource-level progress.

        Args:
            resource: Original active resource.
            done: Original current count or raw offset.
            total: Original reported total or None.
            label: Original visible stage label.
        """
        self.trace.record("progress", "message", (resource, done, total, label))

    def cancel(self) -> bool:
        """Observe original durable cancellation boundaries.

        Returns:
            True only at the configured first cancellation point.
        """
        self.cancel_calls += 1
        value = self.profile == "cancel" and self.cancel_calls == 3
        self.trace.record("cancel", "read", value)
        return value

    def wait(self, notice: legacy.RetryNotice) -> bool:
        """Observe original retry notices and optional interactive cancellation.

        Args:
            notice: Original complete scheduled retry.

        Returns:
            Original retry decision.
        """
        self.trace.record("wait", "choice", notice)
        return self.profile != "cancel-wait"

    def sleep(self, delay: float) -> None:
        """Observe original noninteractive retry waits without wall-clock delay.

        Args:
            delay: Original requested blocking delay.
        """
        self.trace.record("sleep", "wait", delay)

    def snapshot(self) -> dict[str, Json]:
        """Read accepted original files and live fake authority after every run.

        Returns:
            Complete original accepted file contents and canonical live facts.
        """
        files: dict[str, Json] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(self.root))] = path.read_text().replace(
                    str(self.root), "<TMP>"
                )
        remote = {
            "albums": self.spotify.albums,
            "tracks": self.spotify.tracks,
            "artists": self.spotify.artists,
        }
        return {"files": files, "remote": encode_value(remote, self.root)}


def _spotify(profile: str) -> fake.FakeSpotify:
    albums = [fake.album("a"), fake.album("b")]
    tracks = [fake.track(str(index)) for index in range(11)]
    artists = [fake.artist("a"), fake.artist("b")]
    if profile == "empty":
        return fake.FakeSpotify()
    if profile == "duplicates":
        albums.append(fake.album("a", "Newest"))
    return fake.FakeSpotify(
        albums=albums,
        tracks=tracks,
        artists=artists,
        album_errors=[500, 502] if profile in {"server-retry", "cancel-wait"} else [],
        artist_errors=[502] if profile == "artist-fallback" else [],
        add_album_during_scan=fake.album("added") if profile == "additions" else None,
        add_artist_during_reconciliation=fake.artist("added")
        if profile == "additions"
        else None,
    )


def _paths(root: Path, kind: str) -> legacy.LibraryAnalysisPaths:
    mode: legacy.AnalysisMode = "mirrors"
    if kind == "export":
        mode = "async"
    if kind == "sync":
        mode = "sync"
    return legacy.LibraryAnalysisPaths.for_files_dir(root, mode)


def _prepare(paths: legacy.LibraryAnalysisPaths, profile: str) -> None:
    paths.files_dir.mkdir(parents=True, exist_ok=True)
    library = YourLibraryFile(
        albums=[fake.album("b"), fake.album("a"), fake.album("a")],
        tracks=[fake.track("1"), fake.track("0")],
        artists=[fake.artist("b"), fake.artist("a")],
    )
    if profile == "empty":
        library = YourLibraryFile(albums=[], tracks=[], artists=[])
    if profile != "no-export":
        paths.your_library.write_text(library.model_dump_json())
    _seed_mirrors(paths)


def _seed_mirrors(paths: legacy.LibraryAnalysisPaths) -> None:
    paths.albums_total.write_text(
        json.dumps([fake.album("old").model_dump(), fake.album("a").model_dump()])
    )
    paths.liked_tracks_total.write_text(json.dumps([fake.track("old").model_dump()]))
    paths.artists_total.write_text(
        json.dumps([fake.artist("old").model_dump(), fake.artist("a").model_dump()])
    )
    paths.stats_history.write_text("{}")


def _utc_now() -> str:
    return "2026-09-24T12:00:00+00:00"


def _stats_key() -> str:
    return "2026.09.24"


def _fingerprint(path: Path) -> dict[str, int]:
    try:
        return {"size": path.stat().st_size, "mtime_ns": 99}
    except OSError as exc:
        raise legacy.LibrarySyncError(f"Your Library export not found: {path}") from exc


def _publish(edge: AnalysisObservations, path: Path, source: str = "") -> None:
    edge.trace.record("publish", "accepted", (path, source, path.read_text()))


def _watch(patch: pytest.MonkeyPatch, edge: AnalysisObservations) -> None:
    patch.setattr(legacy, "new_run_id", edge.run_id)
    patch.setattr(legacy, "utc_now", _utc_now)
    patch.setattr(legacy, "current_stats_history_key", _stats_key)
    patch.setattr(legacy, "export_fingerprint", _fingerprint)
    patch.setattr(legacy, "publish_managed_path", partial(_publish, edge))
    _watch_files(patch, edge.trace)
    for name in (
        "current_user_saved_albums",
        "current_user_saved_tracks",
        "current_user_followed_artists",
        "current_user_following_artists",
    ):
        edge.trace.watch(patch, edge.spotify, name, name)


def _watch_files(patch: pytest.MonkeyPatch, trace: Trace) -> None:
    for name in (
        "load_json",
        "write_json_atomic",
        "append_event",
        "write_models",
        "append_models_jsonl",
        "load_model_list",
        "load_models_jsonl",
    ):
        trace.watch(patch, legacy, name, name)


def _invoke(
    edge: AnalysisObservations, kind: str, full: bool
) -> legacy.LibrarySyncSummary:
    paths = _paths(edge.root, kind)
    progress = None if edge.profile == "no-progress" else edge.progress
    if kind == "export":
        return legacy.analyse_library_async_routine(
            edge.echo, progress, edge.cancel, paths
        )
    if kind == "sync":
        return legacy.analyse_library_sync_routine(
            cast(Spotify, edge.spotify),
            edge.echo,
            progress,
            edge.wait,
            edge.cancel,
            paths,
            edge.sleep,
            0,
            0,
        )
    if kind == "mirrors":
        return legacy.refresh_live_library_mirrors_routine(
            cast(Spotify, edge.spotify),
            edge.echo,
            progress,
            edge.wait,
            edge.cancel,
            paths,
            edge.sleep,
            0,
            0,
            full,
        )
    return legacy.refresh_live_library_resource_routine(
        cast(Spotify, edge.spotify),
        cast(legacy.ResourceName, kind),
        edge.echo,
        progress,
        edge.wait,
        edge.cancel,
        paths,
        edge.sleep,
        0,
        0,
        full,
    )


def outcome(
    kind: str,
    profile: str = "normal",
    full: bool = False,
    fault: Fault | None = None,
    resume: bool = False,
    runner: Callable[
        [AnalysisObservations, str, bool], legacy.LibrarySyncSummary
    ] = _invoke,
) -> dict[str, Json]:
    """Observe original complete files, source authority and failure/restart traces.

    Args:
        kind: Original complete export/live or independent resource operation.
        profile: Original raw source or interruption input.
        full: Original incremental versus complete mirror behavior.
        fault: Original optional effect failure before or after acceptance.
        resume: Whether to replay using the accepted durable files.
        runner: Original compatibility facade or independently injected runner.

    Returns:
        Complete original deterministic effect and durable-byte observations.
    """
    with TemporaryDirectory() as directory:
        root = Path(directory)
        trace = Trace(root, fault)
        edge = AnalysisObservations(profile, root, trace, _spotify(profile))
        _prepare(_paths(root, kind), profile)
        return _observe_runs(edge, kind, full, resume, runner)


def _observe_runs(
    edge: AnalysisObservations,
    kind: str,
    full: bool,
    resume: bool,
    runner: Callable[[AnalysisObservations, str, bool], legacy.LibrarySyncSummary],
) -> dict[str, Json]:
    snapshots: list[Json] = []
    with pytest.MonkeyPatch.context() as patch:
        _watch(patch, edge)
        for _attempt in range(2 if resume else 1):
            edge.trace.invoke(partial(runner, edge, kind, full))
            snapshots.append(edge.snapshot())
    return {
        "trace": cast(list[Json], edge.trace.events),
        "snapshots": snapshots,
        "fault_fired": edge.trace.fired,
    }


def cases() -> list[dict[str, object]]:
    """Read original complete library workflow observations.

    Returns:
        Original inputs, effects and accepted durable bytes.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))
