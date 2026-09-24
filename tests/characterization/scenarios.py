"""Reusable legacy fixtures; future use cases must satisfy the same recordings."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path
from types import ModuleType

import pytest

from spotify_manager import loaders_savers
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.processors import library_lookups
from spotify_manager.routines import analyse_library
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import release_check
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import the_queue
from spotify_manager.routines import upload_library_files
from tests.routines import test_analyse_library as analysis_fakes
from tests.routines import test_new_kids as kids_fakes
from tests.routines import test_new_wine as wine_fakes
from tests.routines import test_palace_of_memory as palace_fakes
from tests.routines import test_release_check as release_fakes
from tests.routines import test_requeue_for_a_dream as requeue_fakes
from tests.routines import test_review_album_limits as album_fakes
from tests.routines import test_scrobble_history as history_fakes
from tests.routines import test_slow_listening as slow_fakes
from tests.routines import test_the_queue as queue_fakes
from tests.routines.test_upload_library_files import FakeHfApi
from tests.routines.test_upload_library_files import write_json
from tests.support.effects import Trace


type PlaylistFake = (
    wine_fakes.FakeSpotify
    | slow_fakes.FakeSpotify
    | kids_fakes.FakeSpotify
    | queue_fakes.FakeSpotify
)


@dataclass
class Scenario:
    """Bind a routine invocation and an observation of its fake remote state.

    Args:
        operation: Routine with fixture arguments bound; accepts dry_run if supported.
        remote: Callable returning the current remote state after each invocation.
        supports_dry_run: Whether the routine accepts dry_run.
    """

    operation: Callable[..., object]
    remote: Callable[[], object]
    supports_dry_run: bool = True

    def run(self, dry_run: bool) -> object:
        """Invoke the routine against the same fixture state on every restart.

        Args:
            dry_run: Whether to request a preview from routines that support it.

        Returns:
            The routine's unmodified result.

        Raises:
            RuntimeError: The routine or a configured effect interruption fails.
            OSError: The routine cannot read or write an artifact.
        """
        if self.supports_dry_run:
            return self.operation(dry_run=dry_run)
        return self.operation()


def effects(
    patch: pytest.MonkeyPatch,
    trace: Trace,
    spotify: object,
    module: ModuleType,
    *,
    audit: str = "append_log",
    state: str = "save_state",
) -> None:
    """Record the mutation and persistence boundaries available in this family.

    Args:
        patch: Per-test patch manager.
        trace: Recorder receiving effect observations.
        spotify: Mutable fake Spotify client.
        module: Routine module whose persistence calls are observed.
        audit: Name of its audit writer.
        state: Name of its checkpoint writer.
    """
    for name in (
        "_post",
        "_delete",
        "current_user_saved_albums_add",
        "current_user_saved_albums_delete",
        "user_follow_artists",
    ):
        if hasattr(spotify, name):
            trace.watch(patch, spotify, name, f"spotify.{name}")
    for name, operation in ((state, "checkpoint"), (audit, "audit")):
        if hasattr(module, name):
            trace.watch(patch, module, name, operation)


def _requeue_remote(spotify: requeue_fakes.FakeSpotify) -> dict[str, object]:
    return {
        "playlist": [track["id"] for track in spotify.playlist],
        "mutations": spotify.mutations,
    }


def _playlists_remote(spotify: PlaylistFake) -> dict[str, object]:
    playlists = {}
    for name, tracks in spotify.playlists.items():
        playlists[name] = [track["id"] for track in tracks]
    return {"playlists": playlists, "mutations": spotify.mutations}


def _album_remote(spotify: album_fakes.FakeSpotify) -> dict[str, object]:
    return {"deleted": spotify.deleted, "followed": spotify.followed}


def _history_remote(lastfm: history_fakes.FakeLastFm) -> dict[str, object]:
    return {"lastfm_calls": lastfm.calls}


def _palace_remote(spotify: palace_fakes.FakeSpotify) -> dict[str, object]:
    return {"playlist": spotify.playlist_tracks, "posts": spotify.posts}


def _analysis_remote(spotify: analysis_fakes.FakeSpotify) -> dict[str, object]:
    return {
        "album_offsets": spotify.album_calls,
        "track_offsets": spotify.track_calls,
        "artist_cursors": spotify.artist_calls,
    }


def _upload_remote(api: FakeHfApi) -> dict[str, object]:
    return {"operations": api.operations, "message": api.commit_message}


def _release_remote(
    spotify: release_fakes.FakeSpotify,
    history_dry_runs: list[bool],
) -> dict[str, object]:
    return {
        "posts": spotify.posts,
        "puts": spotify.puts,
        "history_dry_runs": history_dry_runs,
    }


def requeue(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed a requeue operation with ordered additions and removals.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its mutable fake state.
    """
    spotify, _, _ = requeue_fakes.configured_spotify()
    effects(patch, trace, spotify, requeue_for_a_dream, audit="_append_log")
    operation = partial(_run_requeue, spotify, root, trace)
    return Scenario(operation, partial(_requeue_remote, spotify))


def _run_requeue(
    spotify: requeue_fakes.FakeSpotify,
    root: Path,
    trace: Trace,
    dry_run: bool,
) -> object:
    return requeue_for_a_dream.flush_requeue_for_a_dream(
        spotify,
        "playlist",
        dry_run=dry_run,
        log_path=root / "log.jsonl",
        echo=partial(trace.record, "echo", "message"),
    )


def _seed_progression(
    spotify: PlaylistFake, fixtures: ModuleType, playlist: str
) -> None:
    """Seed one album using the family's existing release and track builders.

    Args:
        spotify: Mutable progression fake to populate.
        fixtures: Legacy test module providing raw_release and raw_track.
        playlist: Playlist that initially contains the album's first track.
    """
    release = fixtures.raw_release("album", "Album", artist_id="artist")
    tracks = []
    for index in range(1, 4):
        track = fixtures.raw_track(
            f"t{index}",
            f"Track {index}",
            release,
            artist_id="artist",
            track_number=index,
        )
        tracks.append(track)
    spotify.release_tracks["album"] = tracks
    spotify.artist_releases["artist"] = [release]
    spotify.playlists[playlist] = [tracks[0]]


def _run_wine(
    spotify: wine_fakes.FakeSpotify,
    root: Path,
    trace: Trace,
    dry_run: bool,
) -> object:
    paths = wine_fakes.paths(root)
    return new_wine.flush_new_wine(
        spotify,
        "new",
        "sauv",
        trace.choices("choice"),
        dry_run=dry_run,
        echo=partial(trace.record, "echo", "message"),
        state_path=paths["state_path"],
        log_path=paths["log_path"],
        albums_path=paths["albums_path"],
        removed_albums_log_path=paths["removed_albums_log_path"],
    )


def wine(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed the first track of a New Wine album.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its mutable fake state.
    """
    spotify = wine_fakes.FakeSpotify()
    _seed_progression(spotify, wine_fakes, "new")
    effects(patch, trace, spotify, new_wine)
    return Scenario(
        partial(_run_wine, spotify, root, trace), partial(_playlists_remote, spotify)
    )


def _run_slow(
    spotify: slow_fakes.FakeSpotify,
    root: Path,
    trace: Trace,
    dry_run: bool,
) -> object:
    paths = slow_fakes.paths(root)
    return slow_listening.flush_slow_listening(
        spotify,
        "slow",
        trace.wrap("order", slow_fakes.default_order),
        completion_notifier=trace.choices("completion", None),
        dry_run=dry_run,
        echo=partial(trace.record, "echo", "message"),
        state_path=paths["state_path"],
        log_path=paths["log_path"],
    )


def slow(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed the first track of a Slow Listening album.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its mutable fake state.
    """
    spotify = slow_fakes.FakeSpotify()
    _seed_progression(spotify, slow_fakes, "slow")
    effects(patch, trace, spotify, slow_listening)
    return Scenario(
        partial(_run_slow, spotify, root, trace), partial(_playlists_remote, spotify)
    )


def _run_kids(
    spotify: kids_fakes.FakeSpotify,
    root: Path,
    trace: Trace,
    dry_run: bool,
) -> object:
    paths = kids_fakes.isolated_paths(root)
    return new_kids.flush_new_kids(
        spotify,
        "new",
        "queue",
        "great",
        "unlucky",
        "newfoundland",
        trace.choices("choice"),
        year=2026,
        dry_run=dry_run,
        echo=partial(trace.record, "echo", "message"),
        state_path=paths["state_path"],
        log_path=paths["log_path"],
        albums_path=paths["albums_path"],
        artists_path=paths["artists_path"],
        removed_albums_log_path=paths["removed_albums_log_path"],
        scrobbles_path=paths["scrobbles_path"],
    )


def kids(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed a New Kids artist with one liked track and a queued successor.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its mutable fake state.
    """
    spotify = kids_fakes.FakeSpotify()
    tracks = kids_fakes.seed_artist(
        spotify, "artist", release_count=2, tracks_per_release=3
    )
    spotify.playlists["new"] = [tracks[0][0]]
    spotify.liked_ids.add("artist-r1-t1")
    effects(patch, trace, spotify, new_kids, audit="append_event")
    return Scenario(
        partial(_run_kids, spotify, root, trace), partial(_playlists_remote, spotify)
    )


def queue(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed an artist's first track in The Queue.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its mutable fake state.
    """
    paths = queue_fakes.isolated_paths(root)
    spotify = queue_fakes.FakeSpotify()
    tracks = queue_fakes.seed_artist(spotify, "artist")
    spotify.playlists["queue"] = [tracks[0]]
    effects(patch, trace, spotify, the_queue, audit="append_event")
    operation = partial(
        the_queue.flush_queue,
        spotify,
        queue_fakes.queue_playlists(),
        echo=partial(trace.record, "echo", "message"),
        state_path=paths["state_path"],
        log_path=paths["log_path"],
        artists_path=paths["artists_path"],
    )
    return Scenario(operation, partial(_playlists_remote, spotify))


def _album_details(identity: str) -> dict[str, object]:
    return {
        "id": identity,
        "name": "OK Computer",
        "artists": [{"id": "art1", "name": "Radiohead"}],
    }


def _album_tracks() -> list[dict[str, str]]:
    tracks = []
    for index in range(1, 4):
        tracks.append(
            {
                "id": f"t{index}",
                "name": f"Track {index}",
                "uri": f"spotify:track:t{index}",
            }
        )
    return tracks


def album(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed live album evaluation at the legacy floor threshold.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory, unused for this read-only routine.
        trace: Recorder for this scenario.

    Returns:
        A repeatable live evaluation without a dry-run mode.
    """
    spotify = album_fakes.FakeSpotify(saved_tracks={"t1"}, album_tracks=_album_tracks())
    patch.setattr(spotify, "album", _album_details)
    trace.watch(patch, spotify, "album", "spotify.album")
    trace.watch(patch, spotify, "album_tracks", "spotify.album_tracks")
    trace.watch(
        patch, spotify, "current_user_saved_tracks_contains", "spotify.contains"
    )
    operation = partial(library_lookups.evaluate_album_live, spotify, album_id="alb1")
    return Scenario(operation, partial(_album_remote, spotify), supports_dry_run=False)


def history(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed export and delta history with one new Last.fm scrobble.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable refresh sharing its files and fake client.
    """
    history_fakes.write_export(root / "lastfm.json")
    history_fakes.write_legacy_delta(root / "recent.jsonl")
    lastfm = history_fakes.FakeLastFm(
        (LastFmRecentTrack("Live Artist", "Live Track", "Live Album", 3),)
    )
    trace.watch(patch, lastfm, "recent_tracks", "lastfm.read")
    trace.watch(patch, scrobble_history, "_write_export_atomic", "mirror")
    trace.watch(patch, scrobble_history, "_append_log", "audit")
    operation = partial(
        scrobble_history.refresh_scrobble_history,
        lastfm,
        expected_username="man-et-arms",
        export_path=root / "lastfm.json",
        legacy_delta_path=root / "recent.jsonl",
        backup_dir=root / "backups",
        log_path=root / "log.jsonl",
        now=datetime(2026, 9, 24, 12, tzinfo=UTC),
    )
    return Scenario(operation, partial(_history_remote, lastfm))


class MutablePalaceSpotify(palace_fakes.FakeSpotify):
    """Extend the Palace recorder so restarted reads see accepted playlist writes."""

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, str]:
        """Record an accepted write and expose the added tracks to later reads.

        Args:
            path: Spotify playlist endpoint.
            payload: Track URIs to append.

        Returns:
            The original fake's response.
        """
        result = super()._post(path, payload)
        uris = payload["uris"]
        assert isinstance(uris, list)
        for uri in uris:
            assert isinstance(uri, str)
            self.playlist_tracks.append({"id": uri.rsplit(":", 1)[-1], "uri": uri})
        return result


def palace(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed deterministic Palace selection with mutable playlist state.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable invocation sharing its files and fake client.
    """
    palace_fakes.write_albums(root / "albums.json")
    palace_fakes.write_history(root / "history.json")
    spotify = MutablePalaceSpotify()
    effects(patch, trace, spotify, palace_of_memory, audit="_append_log")
    trace.watch(patch, palace_of_memory, "_append_refresh_log", "mirror.audit")
    operation = partial(
        palace_of_memory.fill_palace_of_memory,
        spotify,
        "palace",
        today=date(2026, 8, 4),
        albums_path=root / "albums.json",
        scrobbles_path=root / "history.json",
        state_path=root / "state.json",
        log_path=root / "log.jsonl",
        album_backups_dir=root / "backups",
        album_refresh_log_path=root / "refresh.jsonl",
        random_index_reader=trace.wrap("random", palace_fakes.fixed_random_indexes),
        echo=partial(trace.record, "echo", "message"),
    )
    return Scenario(operation, partial(_palace_remote, spotify))


def _fixed_run_id() -> str:
    return "fixture-run"


def _watch_analysis(
    patch: pytest.MonkeyPatch, trace: Trace, spotify: analysis_fakes.FakeSpotify
) -> None:
    for name, operation in (
        ("write_json_atomic", "checkpoint"),
        ("write_models", "mirror"),
        ("append_event", "audit"),
    ):
        trace.watch(patch, analyse_library, name, operation)
    for name in (
        "current_user_saved_albums",
        "current_user_saved_tracks",
        "current_user_followed_artists",
    ):
        trace.watch(patch, spotify, name, f"spotify.{name}")


def analysis(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed library analysis with multiple saved-track pages.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable sync without a dry-run mode.
    """
    spotify = analysis_fakes.FakeSpotify(
        albums=[analysis_fakes.album("a")],
        tracks=[analysis_fakes.track(str(index)) for index in range(11)],
        artists=[analysis_fakes.artist("artist")],
    )
    patch.setattr(analyse_library, "new_run_id", _fixed_run_id)
    _watch_analysis(patch, trace, spotify)
    operation = partial(
        analyse_library.analyse_library_sync_routine,
        spotify,
        paths=analysis_fakes.paths_for(root, "sync"),
        echo=partial(trace.record, "echo", "message"),
        sleep=trace.choices("sleep"),
    )
    return Scenario(
        operation, partial(_analysis_remote, spotify), supports_dry_run=False
    )


def _review_files(patch: pytest.MonkeyPatch, root: Path) -> None:
    stats = {
        review_album_limits.current_stats_history_key(): (
            album_fakes._stats_report().model_dump()
        )
    }
    fixtures: tuple[tuple[str, str, object], ...] = (
        ("TOTAL_ALBUMS_NEW_PATH", "albums.json", [album_fakes._album().model_dump()]),
        ("YOUR_LIBRARY_PATH", "library.json", album_fakes._library().model_dump()),
        ("TOTAL_ARTISTS_PATH", "artists.json", []),
        ("STATS_HISTORY_PATH", "stats.json", stats),
    )
    for name, filename, value in fixtures:
        path = root / filename
        path.write_text(json.dumps(value))
        patch.setattr(loaders_savers, name, path)


def _watch_review(
    patch: pytest.MonkeyPatch, trace: Trace, spotify: album_fakes.FakeSpotify
) -> None:
    effects(
        patch,
        trace,
        spotify,
        review_album_limits,
        audit="append_removed_album_log",
        state="save_review_decisions",
    )
    for name in (
        "save_total_albums_new_file",
        "save_total_artists_file",
        "save_stats_history",
    ):
        trace.watch(patch, review_album_limits, name, f"mirror.{name}")


def review(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Retain follow, prompt, removal, mirror, and audit ordering during review.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable review with scripted answers and shared remote state.
    """
    spotify = album_fakes.FakeSpotify(saved_tracks={"t1"})
    _review_files(patch, root)
    _watch_review(patch, trace, spotify)
    operation = partial(
        review_album_limits.review_album_limits,
        spotify,
        action_reader=trace.choices("prompt", "r", "r"),
        use_cache=False,
        echo=partial(trace.record, "echo", "message"),
        log_path=root / "removed.jsonl",
        decisions_path=root / "decisions.json",
    )
    return Scenario(operation, partial(_album_remote, spotify), supports_dry_run=False)


def _run_upload(api: FakeHfApi, root: Path, dry_run: bool) -> object:
    plan = upload_library_files.prepare_library_files_upload(
        include_lastfm=False,
        files_dir=root,
        repo_id="fixture/space",
    )
    if dry_run:
        return plan
    # The existing fake implements only the Hub operations used by this routine.
    return upload_library_files.upload_library_files(plan, api=api)  # type: ignore[arg-type]


def upload(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed a library-mirror upload to a recording Hub client.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable upload whose accepted commit operations remain observable.
    """
    write_json(root / "YourLibrary.json", {"tracks": [], "albums": [], "artists": []})
    api = FakeHfApi()
    trace.watch(patch, api, "create_commit", "hub.commit")
    trace.watch(patch, api, "list_repo_files", "hub.list")
    return Scenario(partial(_run_upload, api, root), partial(_upload_remote, api))


def _release_spotify() -> release_fakes.FakeSpotify:
    spotify = release_fakes.FakeSpotify()
    spotify.artist_results = {
        "Artist": [release_fakes.raw_artist("artist-id", "Artist")]
    }
    release = release_fakes.raw_release(
        "album", "Album", "artist-id", "Artist", "2026-08-05"
    )
    spotify.catalogs = {"artist-id": [release]}
    track = release_fakes.raw_track("track", "Opener", "artist-id", "Artist")
    spotify.release_tracks = {"album": [track]}
    return spotify


def release(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    """Seed a ranked artist with one eligible new release.

    Args:
        patch: Per-test patch manager.
        root: Temporary artifact directory.
        trace: Recorder for this scenario.

    Returns:
        A repeatable release check sharing history and playlist state.
    """
    artist = release_check.RankedArtist("artist", "Artist", 200, 1)
    history_dry_runs: list[bool] = []
    release_fakes.patch_history_and_ranking(patch, (artist,), history_dry_runs)
    trace.watch(patch, scrobble_history, "refresh_scrobble_history", "history.refresh")
    spotify = _release_spotify()
    effects(patch, trace, spotify, release_check, audit="append_event")
    operation = partial(
        release_check.run_release_check,
        spotify,
        None,  # type: ignore[arg-type]  # History refresh is replaced by the fixture.
        release_check.ReleaseCheckPlaylists("wine", "vintage"),
        expected_username="listener",
        state_path=root / "state.json",
        log_path=root / "log.jsonl",
        now=datetime(2026, 8, 6, tzinfo=UTC),
        export_path=root / "history.json",
        legacy_delta_path=root / "recent.jsonl",
        backup_dir=root / "backups",
        history_log_path=root / "history-log.jsonl",
    )
    return Scenario(operation, partial(_release_remote, spotify, history_dry_runs))


FACTORIES: dict[str, Callable[[pytest.MonkeyPatch, Path, Trace], Scenario]] = {
    "album": album,
    "requeue": requeue,
    "slow": slow,
    "wine": wine,
    "kids": kids,
    "queue": queue,
    "history": history,
    "palace": palace,
    "analysis": analysis,
    "review": review,
    "upload": upload,
    "release": release,
}
