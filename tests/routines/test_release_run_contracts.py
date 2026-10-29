"""Compare complete release workflows with original ordered-effect snapshots."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import tzinfo
from functools import partial
from functools import partialmethod
from pathlib import Path
from typing import Self
from typing import cast
from unittest.mock import AsyncMock

import pytest

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.future_release import FutureRecordMatching
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.application.release_opening import OpenedReleaseRun
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import PlaylistSnapshot
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.interfaces.operations import release_check as release_operations
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckResources
from spotify_manager.routines import composer_playlists
from spotify_manager.routines import release_check as legacy
from tests.support.release_run import PROFILES
from tests.support.release_run import STAMP
from tests.support.release_run import EffectFailureError
from tests.support.release_run import Effects
from tests.support.release_run import opening


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/release_run.json"
FAILURES = (
    "wine",
    "cleanup",
    "vintage",
    "composers",
    "resolve",
    "catalog",
    "first",
    "persist",
    "add:wine",
    "add:vintage",
    "audit:release_checked",
    "clock",
    "audit:run_completed",
)


class FixedClock(datetime):
    """Keep the original final-check clock deterministic."""

    effects: Effects

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Observe the original final successful-check clock.

        Args:
            tz: Original requested timezone.

        Returns:
            Fixed compatible timestamp.
        """
        cls.effects.clock()
        return cls(2026, 9, 25, tzinfo=STAMP.tzinfo).astimezone(tz)


@dataclass(frozen=True)
class OpenedStage:
    """Supply the existing observed startup result without new effects.

    Args:
        context: Original fixture startup result.
        state_access: Original caller-owned state boundary placeholder.
    """

    context: OpenedReleaseRun
    state_access: RoutineState

    async def run(self, dry_run: bool) -> OpenedReleaseRun:
        """Return the same original opening result.

        Args:
            dry_run: Original preview flag.

        Returns:
            Original fixture startup result.
        """
        return self.context


def _open(context: OpenedReleaseRun, *args: object) -> tuple[OpenedStage, OpenedStage]:
    stage = OpenedStage(context, cast(RoutineState, object()))
    return stage, stage


async def _wine(effects: Effects, *args: object) -> PlaylistSnapshot:
    return await effects.wine()


async def _cleanup(
    effects: Effects,
    sp: object,
    destination: str,
    snapshot: PlaylistSnapshot,
    preview: bool,
    retry: object,
) -> tuple[int, PlaylistMembership]:
    return await effects.cleanup(snapshot, preview)


async def _vintage(effects: Effects, *args: object) -> PlaylistMembership:
    return await effects.vintage()


async def _composers(effects: Effects, *args: object) -> tuple[OwnedPlaylist, ...]:
    return await effects.composers()


def _resolve(
    effects: Effects, sp: object, artist: RankedArtist, reader: object, retry: object
) -> SpotifyArtistCandidate | str | None:
    return effects.resolve(artist)


async def _catalog(
    effects: Effects,
    sp: object,
    artist: RankedArtist,
    mapped: SpotifyArtistCandidate,
    start: object,
    retry: object,
) -> tuple[ReleaseCandidate, ...]:
    from datetime import date

    assert isinstance(start, date)
    return await effects.catalog(artist, mapped, start)


async def _tracks(
    effects: Effects,
    sp: object,
    release: ReleaseCandidate,
    retry: object,
    *,
    first_only: bool = False,
) -> tuple[ReleaseTrack, ...]:
    assert first_only
    track = await effects.first_track(release)
    return () if track is None else (track,)


def _match(
    effects: Effects,
    sp: object,
    track: ReleaseTrack,
    records: tuple[ReleaseCandidate, ...],
    retry: object,
    cache: dict[str, tuple[ReleaseTrack, ...]],
) -> ReleaseCandidate | None:
    return effects.match(track, records, cache)


async def _add(
    effects: Effects,
    sp: object,
    destination: str,
    membership: PlaylistMembership,
    track: ReleaseTrack,
    preview: bool,
    retry: object,
) -> PlaylistAction:
    return await effects.add(destination, membership, track, preview)


def _audit(
    effects: Effects, path: Path, run_id: str, event: str, **details: object
) -> None:
    effects.record_audit(run_id, event, **details)


async def _persist(effects: Effects, access: object, state: dict[str, object]) -> None:
    (await effects.persist(state))


def _bind(
    patch: pytest.MonkeyPatch, context: OpenedReleaseRun, effects: Effects
) -> None:
    patch.setattr(release_operations, "release_opening", partial(_open, context))
    patch.setattr(
        legacy, "_playlist_snapshot", AsyncMock(side_effect=partial(_wine, effects))
    )
    patch.setattr(
        legacy,
        "_deduplicate_wine_cellar",
        AsyncMock(side_effect=partial(_cleanup, effects)),
    )
    patch.setattr(
        legacy,
        "_playlist_membership",
        AsyncMock(side_effect=partial(_vintage, effects)),
    )
    patch.setattr(
        composer_playlists,
        "async_load_owned_playlists",
        AsyncMock(side_effect=partial(_composers, effects)),
    )
    patch.setattr(legacy, "_mapped_artist", effects.decode_mapping)
    patch.setattr(legacy, "_pending_single", effects.decode_pending)
    patch.setattr(
        ArtistMapping,
        "run",
        partialmethod(_resolve_artist, effects),
    )
    patch.setattr(
        legacy,
        "async_load_recent_catalog",
        AsyncMock(side_effect=partial(_catalog, effects)),
    )
    patch.setattr(
        legacy,
        "async_load_release_tracks",
        AsyncMock(side_effect=partial(_tracks, effects)),
    )
    patch.setattr(
        FutureRecordMatching,
        "run",
        partialmethod(_match_record, effects),
    )
    patch.setattr(
        legacy, "_add_to_playlist", AsyncMock(side_effect=partial(_add, effects))
    )
    patch.setattr(legacy, "append_event", partial(_audit, effects))
    patch.setattr(
        legacy, "_persist_state", AsyncMock(side_effect=partial(_persist, effects))
    )
    patch.setattr(FixedClock, "effects", effects, raising=False)
    patch.setattr(legacy, "datetime", FixedClock)


async def observe(
    profile: str, failure: str | None, patch: pytest.MonkeyPatch
) -> dict[str, object]:
    """Observe the complete original runner at deterministic external seams.

    Args:
        profile: Original workflow scenario.
        failure: Optional accepted effect at which to stop.
        patch: Restored test-boundary substitutions.

    Returns:
        Ordered effects, saved checkpoints and the complete result or original error.
    """
    context = opening(profile)
    effects = Effects(profile, failure, context.persisted_state)
    _bind(patch, context, effects)
    outcome: object
    try:
        summary = legacy.run_release_check(
            cast(Spotify, object()),
            cast(legacy.LastFmReader, object()),
            ReleaseCheckOptions(
                playlists=legacy.ReleaseCheckPlaylists("wine", "vintage"),
                expected_username="user",
                dry_run="preview" in profile,
                now=STAMP,
            ),
            ReleaseCheckCallbacks(
                release_choice_reader=effects, progress_callback=effects
            ),
            ReleaseCheckResources(),
        )
        outcome = asdict(summary)
    except (EffectFailureError, legacy.ReleaseCheckError) as exc:
        outcome = {"error": type(exc).__name__, "message": str(exc)}
    return cast(
        dict[str, object],
        json.loads(
            json.dumps(
                {
                    "events": effects.events,
                    "saves": effects.saves,
                    "state": effects.persisted,
                    "outcome": outcome,
                },
                default=str,
            )
        ),
    )


def _fixture() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE.read_text()))


@pytest.mark.parametrize("profile", PROFILES)
async def test_release_runner_original_contract(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve the original complete workflow and restart artifacts.

    Args:
        profile: Original workflow scenario.
        monkeypatch: Isolated external boundaries.
    """
    assert (await observe(profile, None, monkeypatch)) == _fixture()[profile]


@pytest.mark.parametrize("failure", FAILURES)
async def test_release_runner_original_failure_prefix(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve accepted writes and checkpoints when subsequent work fails.

    Args:
        failure: Original accepted effect at which to stop.
        monkeypatch: Isolated external boundaries.
    """
    assert (await observe("album", failure, monkeypatch)) == _fixture()[
        "failure:" + failure
    ]


async def _resolve_artist(
    resources: ArtistMapping,
    effects: Effects,
    artist: RankedArtist,
) -> SpotifyArtistCandidate | str | None:
    return effects.resolve(artist)


async def _match_record(
    resources: FutureRecordMatching,
    effects: Effects,
    track: ReleaseTrack,
    records: tuple[ReleaseCandidate, ...],
    cache: dict[str, tuple[ReleaseTrack, ...]],
) -> ReleaseCandidate | None:
    return effects.match(track, records, cache)
