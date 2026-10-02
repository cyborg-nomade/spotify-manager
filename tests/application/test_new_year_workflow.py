"""Replay original annual outcomes and recovery through independently injected ports."""

from dataclasses import dataclass
from functools import partial
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from spotipy import Spotify

from spotify_manager.application.history_values import ScrobbleHistoryCancelledError
from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_charts import ChartKind
from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_retry import AnnualRetry
from spotify_manager.application.new_year_run import NewYear
from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.application.queue_3_import import resolve_yearly_playlist
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.routines.scrobble_history import LastFmReader
from tests.support.new_year_boundaries import cases
from tests.support.new_year_boundaries import large_outcome
from tests.support.new_year_boundaries import resumed_outcome
from tests.support.new_year_run import AnnualObservations
from tests.support.new_year_run import FixedClock
from tests.support.new_year_run import outcome


@dataclass(frozen=True)
class MemoryAnnualState:
    """Supply original complete detached accepted annual state without storage clients.

    Args:
        edge: Original accepted namespace and failure observations.
    """

    edge: AnnualObservations

    def load(self) -> RetrospectiveState:
        """Read original complete detached authority.

        Returns:
            Original accepted annual records, including unknown fields.
        """
        return cast(RetrospectiveState, self.edge.load())

    def save(self, state: RetrospectiveState, /) -> None:
        """Accept original complete annual checkpoints.

        Args:
            state: Original changed namespace.
        """
        self.edge.save(cast(dict[str, object], state))


@dataclass(frozen=True)
class MemoryAnnual:
    """Supply original complete annual facts and accepted effects through typed ports.

    Args:
        edge: Original configured live/durable observations.
        retry: Original annual cancellation/retry behavior.
    """

    edge: AnnualObservations
    retry: RetryCall

    def destinations(self) -> dict[str, str]:
        """Observe original ordered destination parsing.

        Returns:
            Original exact destination identities.
        """
        return {
            "blast": self.edge.parse("blast"),
            "palace": self.edge.parse("palace"),
            "memory": self.edge.parse("memory"),
            "queue3": self.edge.parse("queue3"),
        }

    def state(self) -> AnnualStateAccess:
        """Supply original annual namespace boundary.

        Returns:
            Original detached in-memory annual access.
        """
        self.edge.record("namespace", "new_year", {"years": {}})
        return MemoryAnnualState(self.edge)

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Supply original current owned facts after accepted creations.

        Returns:
            Original complete current owned observations.
        """
        return self.edge.owned(cast(Spotify, self.edge), self.retry, "queue3")

    def history(self, preview: bool) -> tuple[Scrobble, ...]:
        """Supply original complete full rebuild facts.

        Args:
            preview: Original annual history preview behavior.

        Returns:
            Original canonical annual history.
        """
        refreshed = self.edge.history(
            cast(LastFmReader, self.edge),
            expected_username="listener",
            full_rebuild=True,
            dry_run=preview,
            progress_callback=self.edge.echo,
            cancel_check=self.edge.cancel,
        )
        return refreshed.history

    def playlist(self, identity: str) -> tuple[PlaylistTrack, ...]:
        """Supply original accepted ordered live membership.

        Args:
            identity: Original configured playlist identity.

        Returns:
            Original complete current markers.
        """
        return self.edge.playlist(cast(Spotify, self.edge), identity, self.retry)

    def search(self, item: YearEntry) -> tuple[SpotifyTrackMatch, ...]:
        """Supply original complete approximate/exact search facts.

        Args:
            item: Original ranked artist/title labels.

        Returns:
            Original ordered match qualification facts.
        """
        play = Scrobble(item["name"], item["artist"], "", 0)
        return self.edge.search(cast(Spotify, self.edge), play, self.retry)

    def album(self, artist: str, title: str) -> SpotifyAlbum | None:
        """Supply original complete selected release facts.

        Args:
            artist: Original display artist.
            title: Original release title.

        Returns:
            Original selected release or no match.
        """
        return self.edge.album(cast(Spotify, self.edge), artist, title, self.retry)

    def first(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Supply original first-marker facts.

        Args:
            album: Original selected release.

        Returns:
            Original complete first marker.
        """
        return self.edge.first(cast(Spotify, self.edge), album, self.retry)

    def artist(self, name: str) -> SpotifyArtistCandidate | None:
        """Supply original exact artist mapping without interaction.

        Args:
            name: Original ranked artist display spelling.

        Returns:
            Original mapping or cancellation.
        """
        return self.edge.artist(cast(Spotify, self.edge), name, None, self.retry)

    def primary(self, uri: str) -> object:
        """Supply original retried primary credit facts.

        Args:
            uri: Original prospective marker.

        Returns:
            Original first credited identity.
        """
        raw = cast(
            dict[str, object],
            self.retry(
                partial(self.edge.track, uri), "checking Memory Lane marker artist"
            ),
        )
        return cast(list[dict[str, object]], raw["artists"])[0]["id"]

    def append(self, playlist: str, pending: list[str], top: bool) -> None:
        """Accept original exact missing-marker body.

        Args:
            playlist: Original destination.
            pending: Original fresh absent URI subsequence.
            top: Original top placement.
        """
        payload: dict[str, object] = {"uris": pending}
        if top:
            payload["position"] = 0
        self.edge._post(f"playlists/{playlist}/items", payload)

    def move(self, playlist: str, position: int) -> None:
        """Accept original recalculated single-marker move.

        Args:
            playlist: Original destination.
            position: Original current first occurrence position.
        """
        self.edge._put(
            f"playlists/{playlist}/items",
            {"range_start": position, "insert_before": 0, "range_length": 1},
        )

    def replace(self, playlist: str, uris: list[str]) -> None:
        """Accept original retried complete rank-ordered chart replacement.

        Args:
            playlist: Original chart identity.
            uris: Original unique ranked marker order.
        """
        self.retry(
            partial(self.edge._put, f"playlists/{playlist}/items", {"uris": uris}),
            "synchronizing the yearly chart in scrobble rank order",
        )

    def create(self, name: str, kind: ChartKind, year: int) -> str:
        """Accept original owner read then direct private chart creation.

        Args:
            name: Original chart name.
            kind: Original chart category.
            year: Original source year.

        Returns:
            Original created chart identity.
        """
        user = cast(
            dict[str, str], self.retry(self.edge.current_user, "loading Spotify owner")
        )
        created = self.edge.user_playlist_create(
            user["id"],
            name,
            public=False,
            description=f"Most scrobbled {kind} of {year} on Last.fm.",
        )
        return created["id"]

    def discoveries(self, active_year: int, preview: bool) -> None:
        """Observe original annual discovery import.

        Args:
            active_year: Original source year plus one.
            preview: Original preview behavior.
        """
        self.edge.record("discoveries", "queue3", active_year, preview)


def _cancel(edge: AnnualObservations) -> None:
    if edge.cancel():
        raise ScrobbleHistoryCancelledError("Last.fm history update cancelled.")


def _run(
    edge: AnnualObservations, preview: bool, year: int | None
) -> dict[str, object]:
    cancel = partial(_cancel, edge)
    retry = AnnualRetry(edge.retry, cancel).run
    memory = MemoryAnnual(edge, retry)
    effects = AnnualEffects(
        FixedClock.now,
        memory.destinations,
        memory.state,
        memory.owned,
        resolve_yearly_playlist,
        memory.discoveries,
        cancel,
        edge.echo,
    )
    resolution = AnnualResolution(
        memory.search, memory.album, memory.first, memory.artist, memory.primary
    )
    members = AnnualMembership(memory.playlist, memory.append, memory.move, retry)
    charts = AnnualCharts(
        memory.owned, memory.create, memory.playlist, memory.replace, members, retry
    )
    planner = AnnualPlanning(
        memory.history,
        memory.playlist,
        resolution,
        edge.echo,
        ZoneInfo("Europe/Berlin"),
    )
    return NewYear(effects, planner, AnnualExecution(effects, charts, members)).run(
        year, preview
    )


@pytest.mark.parametrize("case", cases("new_year_run.json"))
def test_annual_injected_workflow_matches_original_complete_outcome(
    case: dict[str, object],
) -> None:
    """Retain original complete plans, accepted effects and failure prefixes.

    Args:
        case: Original immutable configured run.
    """
    profile, failure = cast(str, case["profile"]), cast(str | None, case["failure"])
    preview = bool(case["preview"])
    assert outcome(profile, preview, failure, run=_run) == case["outcome"]
    assert outcome(profile, preview, failure) == case["outcome"]


@pytest.mark.parametrize("case", cases("new_year_recovery.json"))
def test_annual_recovery_matches_original_live_and_durable_authority(
    case: dict[str, object],
) -> None:
    """Retain response-loss retries, saved completion skips and resumed plan authority.

    Args:
        case: Original immutable accepted-boundary replay.
    """
    failure, automatic = cast(str, case["failure"]), bool(case["automatic_retry"])
    assert (
        outcome(
            "normal", False, failure, resume=True, automatic_retry=automatic, run=_run
        )
        == case["outcome"]
    )
    assert (
        outcome("normal", False, failure, resume=True, automatic_retry=automatic)
        == case["outcome"]
    )


@pytest.mark.parametrize("case", cases("new_year_years.json"))
def test_annual_default_and_completed_year_checks_keep_original_preflight(
    case: dict[str, object],
) -> None:
    """Retain default source year and rejection before destination/state reads.

    Args:
        case: Original immutable source year and preview behavior.
    """
    year, preview = cast(int | None, case["year"]), bool(case["preview"])
    assert outcome("normal", preview, None, year=year, run=_run) == case["outcome"]


@pytest.mark.parametrize("case", cases("new_year_resumed_records.json"))
def test_annual_resumed_records_keep_lazy_field_access_and_unknown_result_keys(
    case: dict[str, object],
) -> None:
    """Retain original native failure prefixes and untouched stored result overrides.

    Args:
        case: Original immutable shallow stored plan and completion authority.
    """
    profile, preview = cast(str, case["profile"]), bool(case["preview"])
    assert resumed_outcome(profile, preview, _run) == case["outcome"]
    assert resumed_outcome(profile, preview) == case["outcome"]


@pytest.mark.parametrize("case", cases("new_year_caps.json"))
def test_annual_caps_preserve_uncapped_primary_artist_marker_search(
    case: dict[str, object],
) -> None:
    """Retain fifty/twenty/five caps while resolving an artist outside the top tracks.

    Args:
        case: Original immutable large annual population and complete effects.
    """
    preview = bool(case["preview"])
    observed = large_outcome(preview, _run)
    assert observed == case["outcome"]
    plan = cast(dict[str, object], cast(dict[str, object], observed)["result"])["plan"]
    records = cast(dict[str, list[object]], plan)
    assert (
        len(records["tracks"]),
        len(records["albums"]),
        len(records["artists"]),
    ) == (50, 20, 5)
