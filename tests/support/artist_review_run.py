"""Capture original artist-review decisions, durable effects and failure recovery."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import cast
from unittest.mock import patch

from pydantic import BaseModel
from spotipy import Spotify

from spotify_manager.core.state.compat import RoutineState
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import review_artists as legacy


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/artist_review_run.json"
)
PATHS = legacy.ArtistReviewPaths.for_files_dir(Path("/original/review"))
PLAYLISTS = legacy.QueuePlaylists("one", "two", "three")
PROFILES = (
    "empty",
    "zero-kept",
    "zero-unfollow",
    "unfollow-batch",
    "low-auto",
    "low-tie",
    "low-same-name",
    "low-no-track",
    "middle",
    "high",
    "middle-none",
    "high-none",
    "wrong-first",
    "sticky-one",
    "sticky-two",
    "sticky-three",
    "move",
    "move-no-uri",
    "move-no-id",
    "release-no-uri",
    "skip",
    "quit",
    "decline",
    "invalid",
    "invalid-decline",
    "pending-unfollow",
    "absent-unfollow",
    "pending-move",
    "malformed-move",
    "already-completed",
    "limit-zero",
    "limit-negative",
    "cache-refresh",
    "mixed",
)
FAILURES = (
    "load-artists",
    "load-tracks",
    "state-access",
    "state-load",
    "cache",
    "run-id",
    "events:1",
    "events:2",
    "events:3",
    "events:4",
    "accepted-events:2",
    "accepted-state-save:1",
    "state-save:1",
    "state-save:2",
    "tracks:a",
    "ranked:a",
    "earliest:a",
    "get:one",
    "get:two",
    "get:three",
    "post:one",
    "post:two",
    "post:three",
    "accepted-post:two",
    "delete:me/library",
    "accepted-delete:me/library",
    "delete:one",
    "accepted-delete:one",
    "save-artists",
    "stats",
    "track-choice",
    "release-choice",
    "progress:1",
    "progress:2",
    "progress:3",
    "echo:1",
    "echo:2",
    "echo:3",
)


def clone[T](value: T) -> T:
    """Detach JSON-compatible accepted observations.

    Args:
        value: Original observation to detach.

    Returns:
        Independent JSON-compatible value.
    """
    return cast(T, json.loads(json.dumps(value)))


def artist(identity: str) -> YourLibraryArtist:
    """Build one original followed-artist fact.

    Args:
        identity: Artist identity.

    Returns:
        Complete original library model.
    """
    return YourLibraryArtist(name=identity.upper(), uri=f"spotify:artist:{identity}")


def ranked_track(identity: str, popularity: int = 10) -> legacy.TrackCandidate:
    """Build a primary-credited unliked marker.

    Args:
        identity: Artist identity.
        popularity: Original popularity fact.

    Returns:
        Complete original ranked-track model.
    """
    return legacy.TrackCandidate(
        identity + "-track",
        "Track",
        f"spotify:track:{identity}-track",
        "Album",
        1,
        identity,
        identity.upper(),
        (identity,),
        popularity,
    )


def release(identity: str) -> legacy.ReleaseCandidate:
    """Build a complete checked release with a qualified first marker.

    Args:
        identity: Artist identity.

    Returns:
        Original mutable release model.
    """
    return legacy.ReleaseCandidate(
        identity + "-release",
        "Release",
        f"spotify:album:{identity}-release",
        "Album",
        "2000",
        10,
        1,
        identity,
        identity.upper(),
        (identity,),
        True,
        identity + "-first",
        "First",
        f"spotify:track:{identity}-first",
        identity,
        identity.upper(),
    )


def _raw_marker(identity: str, name: str = "existing") -> dict[str, object]:
    return {
        "id": name,
        "uri": f"spotify:track:{name}",
        "artists": [{"id": identity, "name": identity.upper()}],
    }


def _liked_counts(profile: str) -> tuple[int, ...]:
    if profile == "empty":
        return ()
    if profile == "unfollow-batch":
        return (0,) * 41
    if profile == "mixed":
        return (0, 3, 10, 18)
    if profile.startswith("zero") or "unfollow" in profile:
        return (0,)
    if profile.startswith("high") or profile in {"decline", "sticky-three"}:
        return (18,)
    if profile.startswith("low") or profile in {"sticky-one", "skip", "quit"}:
        return (3,)
    if profile in {"limit-zero", "limit-negative"}:
        return (3, 10)
    return (10,)


@dataclass
class ReviewObservations:
    """Observe original reads, interaction, accepted writes and in-memory authority.

    Args:
        profile: Original decision and checkpoint scenario.
        failure: Optional first failing effect.
        trace: Ordered original observations.
        state: Accepted annual state authority.
        events: Accepted audit events.
        artists: Current canonical followed artists.
        tracks: Current canonical liked tracks.
        playlists: Current fake Spotify membership.
    """

    profile: str
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=legacy._default_state)
    events: list[dict[str, object]] = field(default_factory=list)
    artists: list[YourLibraryArtist] = field(default_factory=list)
    tracks: list[YourLibraryTrack] = field(default_factory=list)
    playlists: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def prepare(self) -> None:
        """Supply original ordered facts and optional interrupted operations."""
        for index, count in enumerate(_liked_counts(self.profile)):
            identity = chr(97 + index) if index < 26 else f"artist-{index}"
            item = artist(identity)
            self.artists.append(item)
            for position in range(count):
                self.tracks.append(
                    YourLibraryTrack(
                        artist=item.name,
                        album="Liked",
                        track="Liked",
                        uri=f"spotify:track:liked-{identity}-{position}",
                    )
                )
        _initial_membership(self)
        _initial_state(self)

    def record(self, action: str, *details: object) -> None:
        """Observe one effect and its original pre-acceptance failure.

        Args:
            action: Original boundary identity.
            details: Complete call observations.

        Raises:
            RuntimeError: This is the configured first failure.
        """
        self.trace.append(clone([action, *details]))
        count = sum(row[0] == action for row in self.trace)
        if self.failure in {action, f"{action}:{count}"}:
            self.failure = None
            raise RuntimeError(f"{action} failed")

    def accepted(self, action: str) -> None:
        """Fail only after a durable effect has been accepted.

        Args:
            action: Original effect identity.

        Raises:
            RuntimeError: The accepted response is lost.
        """
        count = sum(row[0] == action for row in self.trace)
        if self.failure in {f"accepted-{action}", f"accepted-{action}:{count}"}:
            self.failure = None
            raise RuntimeError(f"accepted {action} failed")

    def load_models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Observe original file-model reads.

        Args:
            path: Original configured mirror.
            model: Original complete library model.

        Returns:
            Detached current mirror models.
        """
        if path == PATHS.artists:
            self.record("load-artists", str(path))
            return cast(list[T], [item.model_copy(deep=True) for item in self.artists])
        self.record("load-tracks", str(path))
        return cast(list[T], [item.model_copy(deep=True) for item in self.tracks])

    def state_access(self, *args: object) -> RoutineState:
        """Observe original namespace selection.

        Args:
            args: Original paths and optional state service.

        Returns:
            Offline accepted authority.
        """
        self.record("state-access")
        return cast(RoutineState, self)

    def load(self) -> dict[str, object]:
        """Return detached original accepted progress.

        Returns:
            Original complete serialized checkpoint.
        """
        self.record("state-load")
        return clone(self.state)

    def save(self, value: dict[str, object]) -> None:
        """Accept original state and optionally lose its response.

        Args:
            value: Complete original checkpoint.
        """
        self.record("state-save", value)
        self.state = clone(value)
        self.accepted("state-save")

    def cache(self, path: Path, refresh: bool) -> dict[str, dict[str, object]]:
        """Observe original cache initialization.

        Args:
            path: Original cache location.
            refresh: Original refresh option.

        Returns:
            Empty complete metadata cache.
        """
        self.record("cache", str(path), refresh)
        return {}

    def run_id(self) -> str:
        """Observe original run identity generation.

        Returns:
            Fixed original identifier.
        """
        self.record("run-id")
        return "run-1"

    def append(self, path: Path, events: list[dict[str, object]]) -> None:
        """Accept the original ordered audit bytes as complete event facts.

        Args:
            path: Original audit destination.
            events: Complete ordered events.
        """
        self.record("events", str(path), events)
        self.events.extend(clone(events))
        self.accepted("events")

    def save_artists(self, path: Path, artists: list[YourLibraryArtist]) -> None:
        """Accept the original canonical followed-artist update.

        Args:
            path: Original mirror destination.
            artists: Original remaining artists.
        """
        self.record("save-artists", str(path), [item.model_dump() for item in artists])
        self.artists = [item.model_copy(deep=True) for item in artists]

    def stats(self, path: Path, total: int, removed: int) -> None:
        """Observe original post-unfollow statistics publication.

        Args:
            path: Original statistics destination.
            total: Current followed-artist count.
            removed: Original successful batch size.
        """
        self.record("stats", str(path), total, removed)

    def ranked(
        self, kind: str, item: YourLibraryArtist
    ) -> list[legacy.ReleaseCandidate]:
        """Supply original fully checked release facts.

        Args:
            kind: Original ranked or chronological source.
            item: Original reviewed artist.

        Returns:
            Complete original release candidates.
        """
        self.record(f"{kind}:{item.spotify_id}")
        if self.profile in {"middle-none", "high-none"}:
            return []
        candidate = release(item.spotify_id)
        _alter_release(candidate, self.profile)
        return [candidate]

    def ranked_tracks(self, item: YourLibraryArtist) -> list[legacy.TrackCandidate]:
        """Supply original complete ranked tracks.

        Args:
            item: Original reviewed artist.

        Returns:
            Original complete associated track facts.
        """
        self.record(f"tracks:{item.spotify_id}")
        if self.profile in {"zero-unfollow", "unfollow-batch", "low-no-track"}:
            return []
        tracks = [ranked_track(item.spotify_id)]
        if self.profile in {
            "low-tie",
            "low-same-name",
            "skip",
            "quit",
            "low-invalid",
            "low-auto-tie",
        }:
            second = ranked_track(item.spotify_id + "-second")
            second = legacy.TrackCandidate(
                second.spotify_id,
                second.name,
                second.uri,
                second.album,
                2,
                item.spotify_id,
                item.name,
                (item.spotify_id,),
                9 if self.profile == "low-same-name" else 10,
            )
            tracks.append(second)
        return _alter_tracks(self, tracks)

    def track_choice(
        self, item: YourLibraryArtist, choices: tuple[legacy.TrackCandidate, ...]
    ) -> str:
        """Observe original tied-track interaction.

        Args:
            item: Original reviewed artist.
            choices: Original qualified displayed choices.

        Returns:
            Configured original response.
        """
        self.record("track-choice", item.spotify_id, [asdict(item) for item in choices])
        return _choice(self.profile, choices[-1].spotify_id)

    def release_choice(
        self,
        item: YourLibraryArtist,
        choices: tuple[legacy.ReleaseCandidate, ...],
        decline: bool,
    ) -> str:
        """Observe original release interaction.

        Args:
            item: Original reviewed artist.
            choices: All original displayed candidates.
            decline: Original decline availability.

        Returns:
            Configured original response.
        """
        self.record(
            "release-choice",
            item.spotify_id,
            [asdict(item) for item in choices],
            decline,
        )
        if self.profile in {"choice-clears-id", "move-choice-clears-id"}:
            choices[-1].first_track_id = None
        return _choice(self.profile, choices[-1].spotify_id)

    def progress(self, done: int, total: int, name: str) -> None:
        """Observe original progress.

        Args:
            done: Original current position.
            total: Original pending count.
            name: Original displayed artist or completion label.
        """
        self.record("progress", done, total, name)

    def echo(self, text: str) -> None:
        """Observe the original visible presentation.

        Args:
            text: Original message.
        """
        self.record("echo", text)

    def _get(self, path: str, limit: int, offset: int) -> dict[str, object]:
        playlist = path.split("/")[1]
        self.record(f"get:{playlist}", path, limit, offset)
        items = self.playlists.get(playlist, [])[offset : offset + limit]
        return {
            "items": [{"item": item} for item in items],
            "total": len(self.playlists.get(playlist, [])),
            "next": None,
        }

    def _post(self, path: str, payload: dict[str, list[str]]) -> object:
        playlist = path.split("/")[1]
        self.record(f"post:{playlist}", path, payload)
        for uri in payload["uris"]:
            identity = uri.rsplit(":", 1)[-1].split("-")[0]
            self.playlists.setdefault(playlist, []).append(
                _raw_marker(identity, uri.rsplit(":", 1)[-1])
            )
        self.accepted(f"post:{playlist}")
        return {"snapshot_id": "accepted"}

    def _delete(
        self,
        path: str,
        payload: dict[str, list[dict[str, str]]] | None = None,
        **kwargs: str,
    ) -> object:
        name = path if path == "me/library" else path.split("/")[1]
        self.record(f"delete:{name}", path, payload, kwargs)
        if payload is not None:
            removed = {item["uri"] for item in payload["items"]}
            self.playlists[name] = _without_uris(self.playlists.get(name, []), removed)
        self.accepted(f"delete:{name}")
        return None


def _alter_release(item: legacy.ReleaseCandidate, profile: str) -> None:
    if profile == "wrong-first":
        item.first_track_primary_artist_id = "other"
    if profile == "move-no-id":
        item.first_track_id = None
    if profile == "release-no-uri":
        item.first_track_uri = None


def _choice(profile: str, identity: str) -> str:
    if profile.startswith("release-") and profile in {"release-skip", "release-quit"}:
        return profile.removeprefix("release-")
    if profile in {"skip", "quit", "decline"}:
        return profile
    if profile in {"invalid", "low-invalid"}:
        return "unknown"
    if profile == "invalid-decline":
        return "decline"
    return identity


def _initial_membership(edge: ReviewObservations) -> None:
    target = {"sticky-one": "one", "sticky-two": "two", "sticky-three": "three"}.get(
        edge.profile
    )
    if target:
        edge.playlists[target] = [_raw_marker("a")]
    if edge.profile.startswith("move") or edge.profile.startswith("pending-move"):
        marker = _raw_marker("a")
        if edge.profile == "move-no-uri":
            marker.pop("uri")
        edge.playlists["one"] = [marker]


def _initial_state(edge: ReviewObservations) -> None:
    if edge.profile == "already-completed":
        edge.state["completed_artist_ids"] = ["a"]
    if (
        "unfollow" in edge.profile
        and edge.profile != "zero-unfollow"
        and edge.profile != "unfollow-batch"
    ):
        identity = "absent" if edge.profile == "absent-unfollow" else "a"
        edge.state["pending_unfollows"] = {
            identity: {"artist": "Past", "reason": "past", "liked_tracks": 0}
        }
    if not edge.profile.startswith("pending-move") and edge.profile != "malformed-move":
        return
    plan: dict[str, object] = {"artist": "Past", "liked_tracks": 7}
    if edge.profile.startswith("pending-move"):
        plan.update(
            source_playlist_id="one",
            target_playlist_id="two",
            selected_track_id="a-first",
            selected_track_uri="spotify:track:a-first",
            source_track_uris=["spotify:track:existing"],
            release={"past": True},
        )
        edge.playlists["two"] = [_raw_marker("a", "a-first")]
    edge.state["pending_queue_moves"] = {"a": plan}
    _alter_pending(edge, plan)


def _ranked_bridge(
    edge: ReviewObservations,
    kind: str,
    spotify: Spotify,
    item: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    path: Path,
    retry: legacy.RetryCall,
) -> list[legacy.ReleaseCandidate]:
    return edge.ranked(kind, item)


def _track_bridge(
    edge: ReviewObservations,
    spotify: Spotify,
    item: YourLibraryArtist,
    cache: dict[str, dict[str, object]],
    path: Path,
    retry: legacy.RetryCall,
) -> list[legacy.TrackCandidate]:
    return edge.ranked_tracks(item)


def _timestamp() -> str:
    return "2026-08-08T00:00:00+00:00"


def invoke(edge: ReviewObservations) -> legacy.ArtistReviewSummary:
    """Run the original complete coordinator through frozen external boundaries.

    Args:
        edge: Original live facts and accepted authority.

    Returns:
        Complete original summary.
    """

    limit = {"limit-zero": 0, "limit-negative": -1}.get(edge.profile)
    with ExitStack() as stack:
        _patch_reads(stack, edge)
        return legacy.review_artists(
            cast(Spotify, edge),
            PLAYLISTS,
            None if edge.profile == "low-auto-tie" else edge.track_choice,
            None if edge.profile == "release-auto" else edge.release_choice,
            PATHS,
            edge.echo,
            None if edge.profile == "no-progress" else edge.progress,
            edge.profile == "cache-refresh",
            limit,
        )


def _patch_reads(stack: ExitStack, edge: ReviewObservations) -> None:
    replacements: dict[str, object] = {
        "load_models": edge.load_models,
        "_state_access": edge.state_access,
        "load_cache": edge.cache,
        "new_run_id": edge.run_id,
        "utc_now": _timestamp,
        "append_events": edge.append,
        "save_artists": edge.save_artists,
        "update_stats_after_unfollow": edge.stats,
        "ranked_artist_tracks": partial(_track_bridge, edge),
        "ranked_artist_releases": partial(_ranked_bridge, edge, "ranked"),
        "earliest_artist_releases": partial(_ranked_bridge, edge, "earliest"),
    }
    for name, operation in replacements.items():
        stack.enter_context(patch.object(legacy, name, operation))


def outcome(
    profile: str,
    failure: str | None = None,
    resume: bool = False,
    runner: Callable[[ReviewObservations], legacy.ArtistReviewSummary] = invoke,
) -> dict[str, object]:
    """Observe original result, state, membership and accepted failure prefixes.

    Args:
        profile: Original input scenario.
        failure: Optional failing boundary.
        resume: Whether the same accepted authority is resumed.
        runner: Original facade or independent injected coordinator.

    Returns:
        Complete deterministic original observations.
    """
    edge = ReviewObservations(profile, failure)
    edge.prepare()
    results: list[object] = []
    for _attempt in range(2 if resume else 1):
        try:
            results.append({"summary": asdict(runner(edge))})
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            results.append({"error": type(exc).__name__, "message": str(exc)})
    return clone(
        {
            "results": results,
            "trace": edge.trace,
            "state": edge.state,
            "events": edge.events,
            "playlists": edge.playlists,
            "artists": [item.model_dump() for item in edge.artists],
        }
    )


def cases() -> list[dict[str, object]]:
    """Read immutable original complete-run and recovery evidence.

    Returns:
        Named original input scenarios and observations.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))


def _alter_tracks(
    edge: ReviewObservations, tracks: list[legacy.TrackCandidate]
) -> list[legacy.TrackCandidate]:
    if edge.profile in {"low-collaborator", "zero-non-primary"}:
        return [replace(tracks[0], primary_artist_id="other")]
    if edge.profile == "low-liked":
        return [replace(tracks[0], spotify_id=edge.tracks[0].spotify_id)]
    return tracks


def _alter_pending(edge: ReviewObservations, plan: dict[str, object]) -> None:
    if edge.profile == "pending-move-retained":
        edge.playlists["one"].append(_raw_marker("a", "retained"))
    if edge.profile == "pending-move-bad-count":
        plan["liked_tracks"] = "bad"
    if edge.profile == "pending-move-blank-uri":
        plan["source_track_uris"] = [
            " ",
            "spotify:track:existing",
            "spotify:track:absent",
        ]


def _without_uris(
    items: list[dict[str, object]], removed: set[str]
) -> list[dict[str, object]]:
    remaining = []
    for item in items:
        if item.get("uri") not in removed:
            remaining.append(item)
    return remaining
