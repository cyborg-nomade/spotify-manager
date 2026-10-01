"""Observe Queue fill stages offline before migrating their business coordinator."""

import json
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.routines import found_art
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine
from spotify_manager.routines import release_check
from spotify_manager.routines import the_queue as legacy
from tests.support.queue_neighbors import NOW
from tests.support.queue_neighbors import SEEDS


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/queue_fill.json"
ARTIST = SpotifyArtistCandidate(
    "artist", "Artist", "spotify:artist:artist", 10, 20, 1, True
)
TRACK = CatalogTrack("track", "spotify:track:track", "Track", 1, 1, "artist", "Artist")
RECOMMENDATION = legacy.ArtistRecommendation("Artist", "artist", 1.0, 1.0, ("Seed",), 1)
PLAY = Scrobble("Heard", "Heard", "Album", 1000)


def _initial_state() -> dict[str, object]:
    return {"version": 1, "artist_mappings": {}, "active_flush": None}


@dataclass
class FillObservations:
    """Record original reads, interactions, accepted writes and checkpoints.

    Args:
        scenario: Original boundary scenario.
        failure: Optional accepted effect that raises.
        trace: Ordered original observations.
        state: Caller-owned mutable state.
        checkpoints: Accepted independent snapshots.
    """

    scenario: str
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=_initial_state)
    checkpoints: list[dict[str, object]] = field(default_factory=list)

    def record(self, effect: str, *details: object) -> None:
        """Record original effect arguments before a configured failure.

        Args:
            effect: Observed stage or accepted effect.
            details: Original effect arguments.

        Raises:
            RuntimeError: The configured observed effect fails.
        """
        self.trace.append([effect, *details])
        if effect == self.failure:
            raise RuntimeError(effect)

    def refresh(
        self,
        reader: legacy.LastFmReader,
        *,
        export_path: Path,
        recent_path: Path,
        dry_run: bool,
        now: datetime,
        progress_callback: legacy.Echo | None,
    ) -> tuple[tuple[Scrobble, ...], int]:
        """Observe original history refresh and its status presenter.

        Args:
            reader: Original configured reader.
            export_path: Original export location.
            recent_path: Original recent-history location.
            dry_run: Original preview behavior.
            now: Original effective timestamp.
            progress_callback: Original history status adapter.

        Returns:
            Fixed original plays and live count.
        """
        self.record("history", dry_run, now.isoformat())
        if progress_callback is not None:
            progress_callback("history status")
        return (PLAY,), 2

    def playlist(
        self,
        spotify: Spotify,
        playlist: str,
        retry: legacy.RetryCall,
    ) -> tuple[PlaylistTrack, ...]:
        """Observe the initial Queue membership.

        Args:
            spotify: Original client boundary.
            playlist: Requested Queue identity.
            retry: Original retry boundary.

        Returns:
            Empty original Queue membership.
        """
        self.record("playlist", playlist)
        return ()

    def seeds(
        self,
        history: tuple[legacy.ArtistHistory, ...],
        *,
        seed_count: int,
        week_start: object,
    ) -> tuple[legacy.ArtistSeed, ...]:
        """Observe the original seed selection request.

        Args:
            history: Original aggregated facts.
            seed_count: Original requested number of seeds.
            week_start: Original resolved calendar.

        Returns:
            Fixed original weighted seed.
        """
        self.record("seeds", seed_count, str(week_start))
        return SEEDS[:1]

    def gather(
        self,
        reader: legacy.LastFmReader,
        seeds: tuple[legacy.ArtistSeed, ...],
        heard: set[str],
        **options: object,
    ) -> tuple[legacy.ArtistRecommendation, ...]:
        """Observe candidate gathering before represented-artist reads.

        Args:
            reader: Original configured reader.
            seeds: Original weighted seeds.
            heard: Original heard identities.
            options: Original keyword gathering parameters.

        Returns:
            Fixed original recommendation.
        """
        self.record("candidates", sorted(heard), options["candidate_pool_size"])
        return (RECOMMENDATION,)

    def represented(
        self,
        spotify: Spotify,
        playlists: tuple[str, ...],
        retry: legacy.RetryCall,
    ) -> set[str]:
        """Observe all original representation destinations before state loading.

        Args:
            spotify: Original client boundary.
            playlists: Original ordered representation destinations.
            retry: Original retry boundary.

        Returns:
            Configured original represented identities.
        """
        self.record("represented", playlists)
        return {"artist"} if self.scenario == "represented" else set()

    def load(self) -> dict[str, object]:
        """Observe original state loading.

        Returns:
            Caller-owned original mutable state.
        """
        self.record("load")
        return self.state

    def save(self, state: dict[str, object]) -> None:
        """Accept the original checkpoint before a possible failure.

        Args:
            state: Caller-owned complete original state.
        """
        self.checkpoints.append(deepcopy(state))
        self.record("save")

    def resolve(
        self,
        spotify: Spotify,
        ranked: RankedArtist,
        reader: release_check.ArtistChoiceReader | None,
        retry: legacy.RetryCall,
    ) -> SpotifyArtistCandidate | str | None:
        """Observe original interaction and return configured choice.

        Args:
            spotify: Original client boundary.
            ranked: Original mapping prompt facts.
            reader: Original configured interaction adapter.
            retry: Original retry boundary.

        Returns:
            Original artist, skip, quit or no-match outcome.
        """
        self.record("resolve", asdict(ranked))
        if self.scenario in {"skip", "quit"}:
            return self.scenario
        return None if self.scenario == "no-match" else ARTIST

    def top(
        self,
        spotify: Spotify,
        artist: str,
        retry: legacy.RetryCall,
    ) -> tuple[dict[str, int], tuple[CatalogTrack, ...]]:
        """Observe original top-track facts.

        Args:
            spotify: Original client boundary.
            artist: Original accepted artist identity.
            retry: Original retry boundary.

        Returns:
            Original top tracks in source order.
        """
        self.record("top", artist)
        return {}, (TRACK,)

    def liked(
        self,
        spotify: Spotify,
        tracks: tuple[CatalogTrack, ...],
        retry: legacy.RetryCall,
    ) -> dict[str, bool]:
        """Observe original liked membership.

        Args:
            spotify: Original client boundary.
            tracks: Original top-track window.
            retry: Original retry boundary.

        Returns:
            Original configured liked status.
        """
        self.record("liked", [track.spotify_id for track in tracks])
        return {"track": self.scenario == "all-liked"}

    def current_user_following_artists(self, artists: list[str]) -> list[bool]:
        """Observe original follow-status request.

        Args:
            artists: Original ordered artist identities.

        Returns:
            Original configured follow statuses.
        """
        self.record("following", artists)
        return [] if self.scenario == "bad-follow" else [self.scenario == "followed"]

    def user_follow_artists(self, artists: list[str]) -> None:
        """Accept the original Spotify follow.

        Args:
            artists: Original ordered artist identities.
        """
        self.record("follow", artists)

    def persist(self, artist: SpotifyArtistCandidate, echo: legacy.Echo) -> None:
        """Observe persistence after an accepted follow.

        Args:
            artist: Original accepted artist mapping.
            echo: Original presenter.
        """
        self.record("persist-follow", artist.spotify_id)

    def append(self, spotify: Spotify, playlist: str, uri: str) -> None:
        """Accept the original Queue append.

        Args:
            spotify: Original client boundary.
            playlist: Original Queue identity.
            uri: Original target marker.
        """
        self.record("append", playlist, uri)

    def audit(self, path: Path, event: str, **details: object) -> None:
        """Accept the original completion or rejection event.

        Args:
            path: Original audit location.
            event: Original event name.
            details: Original ordered fields.
        """
        self.record("audit", event, details)

    def echo(self, message: str) -> None:
        """Observe original user-facing completion text.

        Args:
            message: Original presentation text.
        """
        self.record("echo", message)

    def progress(self, done: int, total: int, message: str) -> None:
        """Observe original history and resolution progress.

        Args:
            done: Original completed count.
            total: Original maximum examination count.
            message: Original presentation text.
        """
        self.record("progress", done, total, message)


def _patches(edge: FillObservations) -> tuple[tuple[object, str, object], ...]:
    return (
        (found_art, "refresh_scrobble_history", edge.refresh),
        (new_wine, "load_playlist_tracks", edge.playlist),
        (legacy, "select_seed_artists", edge.seeds),
        (legacy, "gather_artist_recommendations", edge.gather),
        (legacy, "_playlist_artist_ids", edge.represented),
        (release_check, "resolve_spotify_artist", edge.resolve),
        (new_kids, "load_top_track_data", edge.top),
        (legacy, "_liked_statuses", edge.liked),
        (legacy, "_persist_followed_artist", edge.persist),
        (legacy, "add_playlist_item", edge.append),
        (legacy, "append_event", edge.audit),
    )


def _run(edge: FillObservations, preview: bool) -> object:
    with ExitStack() as stack:
        for module, name, callback in _patches(edge):
            stack.enter_context(patch.object(module, name, callback))
        stack.enter_context(patch.object(legacy, "_state_access", return_value=edge))
        result = legacy.fill_queue_from_lastfm(
            cast(Spotify, edge),
            cast(legacy.LastFmReader, edge),
            legacy.QueuePlaylists("queue", "queue2", "new-kids", "queue3", "unlucky"),
            None,
            count=1,
            dry_run=preview,
            now=NOW,
            echo=edge.echo,
            progress_callback=edge.progress,
        )
    return asdict(result)


def original_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Observe the original complete runner and accepted failure prefixes.

    Args:
        scenario: Original configured choice/membership outcome.
        preview: Original preview behavior.
        failure: Optional accepted effect that raises.

    Returns:
        JSON-compatible complete result/error, trace and checkpoint evidence.
    """
    edge = FillObservations(scenario, failure)
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _run(edge, preview)
    except (RuntimeError, legacy.QueueSpotifyError) as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome.update(trace=edge.trace, state=edge.state, checkpoints=edge.checkpoints)
    return json.loads(json.dumps(outcome, default=str))


def cases() -> list[tuple[str, dict[str, object]]]:
    """Read immutable original complete Queue fill observations.

    Returns:
        Named original inputs and complete observed outcomes.
    """
    raw = cast(dict[str, dict[str, object]], json.loads(FIXTURE.read_text()))
    return list(raw.items())
