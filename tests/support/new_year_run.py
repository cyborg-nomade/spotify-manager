"""Freeze original annual preflight, resolution, reconciliation and checkpoints."""

import copy
import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from typing import Self
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.core.state.service import StateNamespace
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_wine
from spotify_manager.routines import new_year as legacy
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import queue_3
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import something_old
from spotify_manager.settings import Settings
from tests.support.discography_boundaries import marker
from tests.support.queue_neighbors import NOW


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/new_year_run.json"
PROFILES = (
    "normal",
    "existing-marker",
    "existing-chart",
    "missing-obsessions",
    "missing-discoveries",
    "duplicate-obsessions",
    "same-id-obsessions",
    "empty-history",
    "no-track",
    "no-exact-track",
    "no-album",
    "no-artist",
    "wrong-primary",
    "done",
    "done-override",
    "resume",
    "changed-settings",
)
FAILURES = (
    "parse:1",
    "parse:4",
    "namespace",
    "load",
    "owned:1",
    "history",
    "search:1",
    "album",
    "first",
    "artist:1",
    "metadata:1",
    "save:1",
    "save:2",
    "save:3",
    "save:4",
    "save:5",
    "save:6",
    "save:7",
    "post:1",
    "accepted-post:1",
    "put:1",
    "accepted-put:1",
    "create:1",
    "accepted-create:1",
    "discoveries",
    "echo:1",
    "echo:8",
    "cancel:1",
    "cancel:2",
    "cancel:7",
    "cancel:20",
    "retry:1",
)


class FixedClock(datetime):
    """Supply the original effective annual clock without changing timezone behavior."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Return the fixed original clock in the requested timezone.

        Args:
            tz: Original effective timezone.

        Returns:
            Complete original effective timestamp.
        """
        return cls.fromtimestamp(NOW.timestamp(), tz=tz)


def plays() -> tuple[Scrobble, ...]:
    """Build original annual ranks with complete primary-marker alternatives.

    Returns:
        Original ordered canonical history.
    """
    timestamp = int(
        datetime.fromisoformat("2025-06-01T12:00:00+02:00").timestamp() * 1000
    )
    return (
        Scrobble("One", "Alpha", "First", timestamp),
        Scrobble("One", "Alpha", "First", timestamp + 1),
        Scrobble("Two", "Beta", "Second", timestamp + 2),
    )


def configuration() -> Settings:
    """Supply original complete destination and account configuration.

    Returns:
        Original caller-owned settings without loading environment files.
    """
    return Settings(
        blast_from_the_past_playlist="blast",
        palace_of_memory_playlist="palace",
        discography_memory_lane_playlist="memory",
        the_queue_3_playlist="queue3",
        lastfm_username="listener",
    )


@dataclass
class AnnualObservations:
    """Observe complete original annual effects and accepted durable/live authority.

    Args:
        profile: Original source, matching or resumed behavior.
        failure: Optional original failing boundary.
        automatic_retry: Whether the original caller retries one failed operation.
        trace: Complete ordered original observations.
        state: Accepted durable annual namespace.
        playlists: Accepted owned playlist identities.
        contents: Accepted ordered live playlist membership.
    """

    profile: str
    failure: str | None = None
    automatic_retry: bool = False
    trace: list[list[object]] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=dict)
    playlists: list[OwnedPlaylist] = field(default_factory=list)
    contents: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize original complete live and annual authority."""
        self.state = {"years": {}}
        self.playlists = [
            OwnedPlaylist("obs", "Obsessions 2025", 1),
            OwnedPlaylist("discoveries", "Great Discoveries 2025", 0),
        ]
        self.contents = {"obs": ["obsession", "obsession"], "memory": ["other"]}
        self._configure()

    def _configure(self) -> None:
        if self.profile == "existing-marker":
            self.contents["memory"] = ["other", "existing-a", "existing-b"]
        if self.profile == "existing-chart":
            self.playlists.append(OwnedPlaylist("old", "top 50 2025 tracks", 1))
            self.contents["old"] = ["outdated"]
        if self.profile == "missing-obsessions":
            self.playlists.pop(0)
        if self.profile == "missing-discoveries":
            self.playlists.pop(1)
        if self.profile in {"duplicate-obsessions", "same-id-obsessions"}:
            identity = "obs" if self.profile == "same-id-obsessions" else "extra"
            self.playlists.append(OwnedPlaylist(identity, "OBSESSIONS 2025", 0))
        if self.profile.startswith("done"):
            self._completed()
        if self.profile in {"resume", "changed-settings"}:
            self.state = {"years": {"2025": _saved_run(self.profile)}}

    def _completed(self) -> None:
        run: dict[str, object] = {
            "completed": ["top tracks"],
            "done": True,
            "extra": "retained",
        }
        if self.profile == "done-override":
            run.update(year=1999, already_completed=False)
        self.state = {"years": {"2025": run}}

    def record(self, action: str, *details: object) -> None:
        """Observe an original boundary before its possible failure.

        Args:
            action: Original observation identity.
            details: Complete original arguments.
        """
        self.trace.append([action, *details])
        self.fail(action)

    def fail(self, action: str) -> None:
        """Inject original failures before or after accepted effects.

        Args:
            action: Original failure boundary.

        Raises:
            RuntimeError: The configured original boundary fails.
        """
        observed = action.removeprefix("accepted-")
        count = sum(row[0] == observed for row in self.trace)
        if observed == "cancel":
            return
        if self.failure in {action, f"{action}:{count}"}:
            raise RuntimeError(f"{self.failure} failed")

    def parse(self, reference: str) -> str:
        """Observe original configured playlist parsing.

        Args:
            reference: Original configured reference.

        Returns:
            Original resolved identity.
        """
        self.record("parse", reference)
        return reference

    def namespace(
        self,
        name: str,
        default: Callable[[], dict[str, object]],
        validator: Callable[[object], dict[str, object]],
    ) -> StateNamespace:
        """Observe original namespace resolution and default authority.

        Args:
            name: Original annual namespace.
            default: Original complete missing-state factory.
            validator: Original shallow validator.

        Returns:
            Original in-memory annual access.
        """
        self.record("namespace", name, default())
        return cast(StateNamespace, self)

    def load(self) -> dict[str, object]:
        """Read a detached copy of original accepted annual authority.

        Returns:
            Original complete mutable annual state.
        """
        self.record("load")
        return copy.deepcopy(self.state)

    def save(self, state: dict[str, object]) -> None:
        """Accept complete annual checkpoints at original boundaries.

        Args:
            state: Original complete changed namespace.
        """
        self.record("save", copy.deepcopy(state))
        self.state = copy.deepcopy(state)
        self.fail("accepted-save")

    def owned(
        self, sp: Spotify, retry: legacy.RetryCall, excluded: str
    ) -> tuple[OwnedPlaylist, ...]:
        """Read current original owned playlists.

        Args:
            sp: Original caller-owned SDK.
            retry: Original annual retry boundary.
            excluded: Original auxiliary playlist exclusion.

        Returns:
            Original current owned facts.
        """
        self.record("owned", excluded)
        return tuple(self.playlists)

    def history(
        self, lastfm: scrobble_history.LastFmReader, **kwargs: object
    ) -> ScrobbleHistorySummary:
        """Supply original full-rebuild results through caller-owned history seams.

        Args:
            lastfm: Original caller-owned history client.
            kwargs: Original rebuild, preview, account and cancellation settings.

        Returns:
            Original complete history refresh summary.
        """
        self.record(
            "history",
            kwargs["expected_username"],
            kwargs["full_rebuild"],
            kwargs["dry_run"],
            kwargs["cancel_check"] is not None,
        )
        history = () if self.profile == "empty-history" else plays()
        return ScrobbleHistorySummary(
            NOW,
            "listener",
            history,
            0,
            0,
            len(history),
            bool(kwargs["dry_run"]),
            False,
            None,
        )

    def playlist(
        self, sp: Spotify, identity: str, retry: legacy.RetryCall
    ) -> tuple[PlaylistTrack, ...]:
        """Read original accepted live ordered markers.

        Args:
            sp: Original SDK boundary.
            identity: Original requested playlist.
            retry: Original caller retry.

        Returns:
            Complete original current marker facts.
        """
        self.record("playlist", identity)
        return tuple(
            marker(uri, _primary(uri), _primary(uri))
            for uri in self.contents.get(identity, [])
        )

    def search(
        self, sp: Spotify, play: Scrobble, retry: legacy.RetryCall
    ) -> tuple[SpotifyTrackMatch, ...]:
        """Supply original approximate/exact Spotify matches in observed order.

        Args:
            sp: Original SDK boundary.
            play: Original requested history title and display artist.
            retry: Original caller retry.

        Returns:
            Complete original matching facts.
        """
        self.record("search", play.artist, play.track, play.album, play.timestamp_ms)
        if self.profile == "no-track":
            return ()
        uri = f"spotify:track:{'a' if play.artist == 'Alpha' else 'b'}-{play.track}"
        exact = 0.9 if self.profile == "no-exact-track" else 1.0
        prefix = "a" if play.artist == "Alpha" else "b"
        return (
            _match(f"spotify:track:{prefix}-Approx", play, 0.8),
            _match(uri, play, exact),
        )

    def album(
        self, sp: Spotify, artist: str, name: str, retry: legacy.RetryCall
    ) -> SpotifyAlbum | None:
        """Supply original exact album mapping or no match.

        Args:
            sp: Original SDK boundary.
            artist: Original expected artist.
            name: Original expected release.
            retry: Original caller retry.

        Returns:
            Original resolved release or none.
        """
        self.record("album", artist, name)
        if self.profile == "no-album":
            return None
        return SpotifyAlbum(name, name, artist, name, False, 1.0)

    def first(
        self, sp: Spotify, album: SpotifyAlbum, retry: legacy.RetryCall
    ) -> SpotifyFirstTrack:
        """Supply original first marker for a resolved release.

        Args:
            sp: Original SDK boundary.
            album: Original selected release.
            retry: Original caller retry.

        Returns:
            Original complete first marker.
        """
        self.record("first", album.spotify_id)
        return SpotifyFirstTrack(album.spotify_id, f"first-{album.spotify_id}", "First")

    def artist(
        self, sp: Spotify, name: str, choice: object, retry: legacy.RetryCall
    ) -> SpotifyArtistCandidate | None:
        """Supply original exact artist mapping or cancellation.

        Args:
            sp: Original SDK boundary.
            name: Original expected display artist.
            choice: Original absent interactive mapping reader.
            retry: Original caller retry.

        Returns:
            Original complete artist mapping or none.
        """
        self.record("artist", name, choice)
        if self.profile == "no-artist":
            return None
        identity = "artist-a" if name == "Alpha" else "artist-b"
        return SpotifyArtistCandidate(identity, name, identity, None, None, 1)

    def track(self, uri: str) -> dict[str, object]:
        """Supply original first-credit facts for prospective Memory Lane markers.

        Args:
            uri: Original prospective URI.

        Returns:
            Original raw primary artist credit.
        """
        self.record("metadata", uri)
        identity = "wrong" if self.profile == "wrong-primary" else _primary(uri)
        return {"artists": [{"id": identity}]}

    def current_user(self) -> dict[str, str]:
        """Read original owner before chart creation.

        Returns:
            Original current owner identity.
        """
        self.record("owner")
        return {"id": "owner"}

    def user_playlist_create(
        self, user: str, name: str, *, public: bool, description: str
    ) -> dict[str, str]:
        """Accept original chart creation before optional lost-response failure.

        Args:
            user: Original owner.
            name: Original chart title.
            public: Original visibility.
            description: Original description.

        Returns:
            Original created identity.
        """
        self.record("create", user, name, public, description)
        identity = f"chart-{len(self.playlists)}"
        self.playlists.append(OwnedPlaylist(identity, name, 0))
        self.fail("accepted-create")
        return {"id": identity}

    def _post(self, path: str, payload: dict[str, object]) -> None:
        """Accept original missing-marker insertion.

        Args:
            path: Original mutation path.
            payload: Original exact SDK body.
        """
        self.record("post", path, copy.deepcopy(payload))
        current = self.contents.setdefault(path.split("/")[1], [])
        position = cast(int, payload.get("position", len(current)))
        current[position:position] = cast(list[str], payload["uris"])
        self.fail("accepted-post")

    def _put(self, path: str, payload: dict[str, object]) -> None:
        """Accept original chart replacement or marker reordering.

        Args:
            path: Original mutation path.
            payload: Original exact SDK body.
        """
        self.record("put", path, copy.deepcopy(payload))
        identity = path.split("/")[1]
        if "uris" in payload:
            self.contents[identity] = list(cast(list[str], payload["uris"]))
            self.fail("accepted-put")
            return
        current = self.contents[identity]
        item = current.pop(cast(int, payload["range_start"]))
        current.insert(cast(int, payload["insert_before"]), item)
        self.fail("accepted-put")

    def discoveries(self, sp: Spotify, destination: str, **kwargs: object) -> None:
        """Observe original annual discovery import.

        Args:
            sp: Original SDK boundary.
            destination: Original auxiliary destination.
            kwargs: Original effective year, preview, service and callbacks.
        """
        self.record(
            "discoveries",
            destination,
            kwargs["active_year"],
            kwargs.get("dry_run", False),
        )

    def echo(self, message: str) -> None:
        """Observe original visible stage text.

        Args:
            message: Original complete text.
        """
        self.record("echo", message)

    def cancel(self) -> bool:
        """Observe original cancellation checks at every retry boundary.

        Returns:
            Whether the configured original boundary requests cancellation.
        """
        self.record("cancel")
        count = sum(row[0] == "cancel" for row in self.trace)
        return self.failure == f"cancel:{count}"

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original caller's single retry after a failed response.

        Args:
            operation: Original complete deferred boundary.
            description: Original retry label.

        Returns:
            Original accepted operation result.
        """
        self.record("retry", description)
        try:
            return operation()
        except RuntimeError:
            if not self.automatic_retry:
                raise
        return operation()


def _primary(uri: str) -> str:
    if uri.startswith("spotify:track:a-") or uri == "existing-a":
        return "artist-a"
    if uri.startswith("spotify:track:b-") or uri == "existing-b":
        return "artist-b"
    return "other"


def _saved_run(profile: str) -> dict[str, object]:
    destinations = {
        "blast": "blast",
        "palace": "palace",
        "memory": "memory",
        "queue3": "queue3",
    }
    if profile == "changed-settings":
        destinations["memory"] = "changed"
    plan = {
        "tracks": [
            {
                "artist": "Alpha",
                "name": "One",
                "scrobbles": 2,
                "uri": "spotify:track:a-One",
            }
        ],
        "albums": [
            {"artist": "Alpha", "name": "First", "scrobbles": 2, "uri": "first-First"}
        ],
        "artists": [
            {
                "artist": "Alpha",
                "name": "Alpha",
                "scrobbles": 2,
                "artist_id": "artist-a",
                "uri": "spotify:track:a-One",
            }
        ],
        "destinations": destinations,
        "obsessions": ["obsession"],
    }
    return {"completed": ["top tracks"], "plan": plan, "extra": "retained"}


def _match(uri: str, play: Scrobble, similarity: float) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        uri, uri, play.track, (play.artist,), "", 1, similarity, None, None
    )


def original_run(
    edge: AnnualObservations, preview: bool, year: int | None
) -> dict[str, object]:
    """Run original annual orchestration through complete observed boundary seams.

    Args:
        edge: Original configured accepted state and live effects.
        preview: Original annual preview behavior.
        year: Original source year or absent default.

    Returns:
        Complete original wide annual outcome.
    """
    bindings = (
        (legacy, "datetime", FixedClock),
        (blast_from_past, "parse_playlist_id", edge.parse),
        (queue_3, "parse_playlist_id", edge.parse),
        (queue_3, "load_owned_playlists", edge.owned),
        (queue_3, "import_previous_year_discoveries", edge.discoveries),
        (legacy.scrobble_history, "refresh_scrobble_history", edge.history),
        (new_wine, "load_playlist_tracks", edge.playlist),
        (blast_from_past, "search_spotify_matches", edge.search),
        (palace_of_memory, "search_spotify_album", edge.album),
        (palace_of_memory, "load_first_track", edge.first),
        (something_old, "resolve_spotify_artist", edge.artist),
    )
    with ExitStack() as stack:
        for module, name, callback in bindings:
            stack.enter_context(patch.object(module, name, callback))
        return legacy.run_new_year(
            cast(Spotify, edge),
            cast(scrobble_history.LastFmReader, edge),
            configuration(),
            year=year,
            dry_run=preview,
            state_service=cast(StateService, edge),
            echo=edge.echo,
            cancel_check=edge.cancel,
            retry_call=edge.retry,
        )


def outcome(
    profile: str,
    preview: bool,
    failure: str | None,
    resume: bool = False,
    automatic_retry: bool = False,
    year: int | None = 2025,
    run: Callable[
        [AnnualObservations, bool, int | None], dict[str, object]
    ] = original_run,
) -> object:
    """Capture original complete outcomes, durable checkpoints and live mutations.

    Args:
        profile: Original configured sources or resolution.
        preview: Original preview behavior.
        failure: Original configured failure boundary.
        resume: Whether to rerun after an original accepted partial failure.
        automatic_retry: Whether original caller retries failed responses.
        year: Original requested completed calendar year.
        run: Original or independently injected annual coordinator.

    Returns:
        Complete JSON-compatible original success/failure and accepted effects.
    """
    edge = AnnualObservations(profile, failure, automatic_retry)
    result: dict[str, object] = {}
    try:
        result["result"] = run(edge, preview, year)
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    if resume:
        edge.failure = None
        result["resumed"] = run(edge, preview, year)
    result.update(trace=edge.trace, state=edge.state, contents=edge.contents)
    return json.loads(json.dumps(result))
