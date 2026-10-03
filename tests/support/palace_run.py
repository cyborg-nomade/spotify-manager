"""Capture original Palace choices, cache reuse, live authority and effect prefixes."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime
from datetime import tzinfo
from functools import partial
from functools import partialmethod
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.bootstrap import palace_cursor
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.history import HistoricalAlbum
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.infrastructure.legacy.palace_run import LegacyPalace
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory as legacy
from tests.support.queue_neighbors import NOW


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/palace_run.json"
SCENARIOS = (
    "normal",
    "override",
    "invalid-override",
    "missing",
    "initial-present",
    "changed",
    "all-present",
    "cursor-identity",
    "empty-history",
)
FAILURES = (
    "refresh",
    "state-load",
    "history",
    "playlist",
    "playlist:2",
    "track",
    "track:3",
    "search",
    "append",
    "state-save",
    "audit",
    "echo",
    "progress:2",
    "progress:8",
    "retry:2",
)


class FixedClock:
    """Supply the original fixed cursor timestamp without changing production state."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        """Return the fixed original observation timestamp.

        Args:
            tz: Original optional timezone.

        Returns:
            Fixed original effective time.
        """
        return NOW if tz is None else NOW.astimezone(tz)


def albums() -> tuple[YourLibraryAlbum, ...]:
    """Build original saved facts without filesystem or live dependencies.

    Returns:
        Seven complete original album models in mirror order.
    """
    result = []
    for index in range(7):
        result.append(
            YourLibraryAlbum(
                artist=f"Artist {index}",
                album=f"Album {index:02d}",
                uri=f"spotify:album:album-{index}",
            )
        )
    return tuple(result)


def history() -> tuple[legacy.HistoricalAlbumSelection, ...]:
    """Build saved, remote and repeated original historical selections.

    Returns:
        Original ordered historical facts.
    """
    result = []
    for index, album in enumerate(
        (
            HistoricalAlbum("Artist 1", "Album 01", 5),
            HistoricalAlbum("Other", "Remote", 3),
            HistoricalAlbum("Other", "Remote", 2),
        )
    ):
        result.append(
            legacy.HistoricalAlbumSelection(
                date(2020 + index, 1, 2), index, 1, 1, album
            )
        )
    return tuple(result)


@dataclass
class PalaceObservations:
    """Observe original stages and accepted failures with complete typed facts.

    Args:
        scenario: Configured original authority or resolution scenario.
        failure: Optional original stage or indexed occurrence that raises.
        trace: Original ordered observations.
        accepted: Original externally accepted playlist identities.
        cursor: Original accepted durable checkpoint, if any.
    """

    scenario: str
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)
    accepted: set[str] = field(default_factory=set)
    cursor: dict[str, object] | None = None

    def record(self, effect: str, *details: object) -> None:
        """Observe a boundary before its configured accepted failure.

        Args:
            effect: Original boundary name.
            details: Original observed arguments.

        Raises:
            RuntimeError: The configured accepted boundary fails.
        """
        self.trace.append([effect, *details])
        count = sum(row[0] == effect for row in self.trace)
        if self.failure in {effect, f"{effect}:{count}"}:
            raise RuntimeError(effect)

    def refresh(
        self, spotify: Spotify, **options: object
    ) -> tuple[tuple[YourLibraryAlbum, ...], legacy.SavedAlbumRefresh]:
        """Supply original live mirror preflight, including preview publication.

        Args:
            spotify: Original caller-owned client.
            options: Original refresh options.

        Returns:
            Original complete refreshed mirror and refresh facts.
        """
        self.record(
            "refresh", str(options["path"]), options["progress_callback"] is not None
        )
        return albums(), legacy.SavedAlbumRefresh(NOW, 6, 7, 1, 0, 0, True, "backup")

    def state(self, path: Path, service: StateService | None) -> RoutineState:
        """Supply caller-owned durable cursor access.

        Args:
            path: Original explicit state path.
            service: Original optional state service.

        Returns:
            In-memory original state boundary.
        """
        self.record("state-access", str(path), service is None)
        return cast(RoutineState, self)

    def load(self) -> dict[str, object]:
        """Read original durable cursor facts.

        Returns:
            Original fallback or authoritative last-album identity.
        """
        self.record("state-load")
        if self.cursor is not None:
            return deepcopy(self.cursor)
        if self.scenario == "cursor-identity":
            return {
                "last_alphabetical_album_id": "album-5",
                "next_alphabetical_index": 1,
            }
        return {"next_alphabetical_index": 1, "unknown": "retained on read"}

    def save(self, payload: dict[str, object]) -> None:
        """Accept the original complete cursor replacement.

        Args:
            payload: Original successful next-position checkpoint.
        """
        self.record("state-save", deepcopy(payload))
        self.cursor = deepcopy(payload)
        if self.failure == "accepted-state":
            self.record("accepted-state")

    def historical(
        self, **options: object
    ) -> tuple[datetime, date, int, tuple[legacy.HistoricalAlbumSelection, ...]]:
        """Supply original Random.org timestamp and historical album facts.

        Args:
            options: Original history selection options.

        Returns:
            Original complete dated historical selection.
        """
        self.record(
            "history",
            str(options["path"]),
            str(options["today"]),
            options["progress_callback"] is not None,
        )
        selected = () if self.scenario == "empty-history" else history()
        return NOW, date(2025, 12, 31), 3, selected

    def playlist(self, spotify: Spotify, identity: str) -> PlaylistState:
        """Supply initial and final live membership authority.

        Args:
            spotify: Original caller-owned client.
            identity: Original destination identity.

        Returns:
            Original configured live membership.
        """
        self.record("playlist", identity)
        count = sum(row[0] == "playlist" for row in self.trace)
        identities = set(self.accepted)
        if self.scenario == "initial-present":
            identities.add("track-album-1")
        if self.scenario == "changed" and count > 1:
            identities.add("track-remote")
        if self.scenario == "all-present":
            identities.update(f"track-album-{index}" for index in range(7))
            identities.add("track-remote")
        return PlaylistState(len(identities), frozenset(identities))

    def first_track(
        self, spotify: Spotify, album: legacy.SpotifyAlbum, retry: legacy.RetryCall
    ) -> legacy.SpotifyFirstTrack:
        """Supply original first tracks and observe run-scoped cache reuse.

        Args:
            spotify: Original caller-owned client.
            album: Original resolved release.
            retry: Original retry boundary.

        Returns:
            Complete original first marker.
        """
        self.record("track", asdict(album))
        identity = f"track-{album.spotify_id}"
        return legacy.SpotifyFirstTrack(identity, f"spotify:track:{identity}", "First")

    def search(
        self, spotify: Spotify, artist: str, album: str, retry: legacy.RetryCall
    ) -> legacy.SpotifyAlbum | None:
        """Supply remote album resolution or an original no-match result.

        Args:
            spotify: Original caller-owned client.
            artist: Original expected artist spelling.
            album: Original expected title.
            retry: Original read retry policy.

        Returns:
            Original resolved remote album or none.
        """
        self.record("search", artist, album)
        if self.scenario == "missing":
            return None
        return legacy.SpotifyAlbum(
            "remote", "spotify:album:remote", artist, album, False, 1.0
        )

    def _post(self, path: str, payload: dict[str, object]) -> None:
        self.record("append", path, payload)
        for uri in cast(list[str], payload["uris"]):
            self.accepted.add(uri.removeprefix("spotify:track:"))
        if self.failure == "accepted-append":
            self.record("accepted-append")

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Retain original caller-owned retry placement around reads and append.

        Args:
            operation: Original pending operation.
            description: Original visible retry label.

        Returns:
            Original operation result.
        """
        self.record("retry", description)
        return operation()

    def audit(self, path: Path, summary: legacy.PalaceOfMemorySummary) -> None:
        """Accept the original completion audit after the cursor checkpoint.

        Args:
            path: Original audit location.
            summary: Original complete outcome.
        """
        self.record("audit", str(path), asdict(summary))

    def progress(self, message: str) -> None:
        """Observe original progress text.

        Args:
            message: Original stage text.
        """
        self.record("progress", message)

    def echo(self, message: str) -> None:
        """Observe original accepted-append presentation.

        Args:
            message: Original completion text.
        """
        self.record("echo", message)


def _patches(edge: PalaceObservations) -> tuple[tuple[object, str, object], ...]:
    return (
        (palace_cursor, "_refresh", partial(_cursor_refresh, edge)),
        (LegacyPalace, "refresh", partialmethod(_refresh, edge)),
        (legacy, "_state_access", edge.state),
        (LegacyPalace, "historical", partialmethod(_historical, edge)),
        (legacy, "load_first_track", edge.first_track),
        (legacy, "search_spotify_album", edge.search),
        (legacy, "_append_log", edge.audit),
        (legacy, "datetime", FixedClock),
        (blast_from_past, "load_playlist_state", edge.playlist),
    )


def _run(edge: PalaceObservations, preview: bool) -> object:
    override = "3" if edge.scenario == "override" else None
    if edge.scenario == "invalid-override":
        override = ""
    with ExitStack() as stack:
        for module, name, callback in _patches(edge):
            stack.enter_context(patch.object(module, name, callback))
        result = legacy.fill_palace_of_memory(
            cast(Spotify, edge),
            "destination",
            dry_run=preview,
            alphabetical_start=override,
            today=date(2026, 8, 8),
            albums_path=Path("albums"),
            scrobbles_path=Path("history"),
            state_path=Path("cursor"),
            log_path=Path("audit"),
            retry_call=edge.retry,
            progress_callback=edge.progress,
            echo=edge.echo,
        )
    return asdict(result)


def original_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Observe the original complete runner before its application extraction.

    Args:
        scenario: Original configured membership or resolution behavior.
        preview: Original preview behavior.
        failure: Optional original accepted boundary failure.

    Returns:
        JSON-compatible original complete result/error and effect prefix.
    """
    edge = PalaceObservations(scenario, failure)
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _run(edge, preview)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


def cases() -> list[dict[str, object]]:
    """Read immutable original Palace outcomes and accepted-effect prefixes.

    Returns:
        Complete original inputs and observations.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))


def recovery_outcome(failure: str) -> object:
    """Replay original accepted effects and durable authority across a fresh run.

    Args:
        failure: Original first-run boundary failure.

    Returns:
        Complete original failure, resumed result and combined ordered trace.
    """
    edge = PalaceObservations("normal", failure)
    outcome: dict[str, object] = {}
    try:
        _run(edge, False)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    edge.failure = None
    outcome["result"] = _run(edge, False)
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


def cursor_outcome(position: int, failure: str | None) -> object:
    """Observe original manual cursor refresh and checkpoint ordering.

    Args:
        position: Original one-based requested position, including boundary values.
        failure: Original accepted stage that fails, if any.

    Returns:
        Complete original cursor outcome and effect prefix.
    """
    edge = PalaceObservations("normal", failure)
    result: dict[str, object] = {}
    try:
        result["result"] = _cursor_run(edge, position)
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


def _cursor_run(edge: PalaceObservations, position: int) -> object:
    with ExitStack() as stack:
        for module, name, callback in _patches(edge):
            stack.enter_context(patch.object(module, name, callback))
        result = legacy.set_alphabetical_cursor(
            cast(Spotify, edge),
            position,
            albums_path=Path("albums"),
            state_path=Path("cursor"),
            retry_call=edge.retry,
            progress_callback=edge.progress,
        )
    return {
        "next_index": result.next_index,
        "next_album": result.next_album.model_dump(),
        "album_refresh": asdict(result.album_refresh),
    }


def _refresh(
    resources: LegacyPalace,
    edge: PalaceObservations,
) -> tuple[tuple[YourLibraryAlbum, ...], legacy.SavedAlbumRefresh]:
    return edge.refresh(
        resources.spotify,
        path=resources.albums_path,
        backups_dir=resources.backups_dir,
        log_path=resources.refresh_log,
        retry_call=resources.retry,
        progress_callback=resources.callback,
    )


def _historical(
    resources: LegacyPalace,
    edge: PalaceObservations,
) -> tuple[datetime, date, int, tuple[legacy.HistoricalAlbumSelection, ...]]:
    return edge.historical(
        path=resources.scrobbles_path,
        today=resources.today,
        random_index_reader=resources.random_reader,
        progress_callback=resources.callback,
    )


def _cursor_refresh(
    edge: PalaceObservations,
    spotify: Spotify,
    path: Path,
    backups: Path,
    log_path: Path,
    retry: legacy.RetryCall,
    callback: legacy.ProgressCallback | None,
) -> tuple[tuple[YourLibraryAlbum, ...], legacy.SavedAlbumRefresh]:
    return edge.refresh(
        spotify,
        path=path,
        backups_dir=backups,
        log_path=log_path,
        retry_call=retry,
        progress_callback=callback,
    )
