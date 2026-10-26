"""Compose Sauvignon with original clock, settings and caller-owned effects."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.sauvignon_run import SauvignonRun
from spotify_manager.application.sauvignon_run import SauvignonStages
from spotify_manager.application.sauvignon_selection import AlbumEditionChoice
from spotify_manager.bootstrap.recommendations import candidate_gathering
from spotify_manager.bootstrap.recommendations import recommendation_seeds
from spotify_manager.infrastructure.legacy.sauvignon import LegacySauvignon
from spotify_manager.routines import sauvignon as legacy


@dataclass(frozen=True)
class SauvignonClock:
    """Observe the original effective UTC timestamp.

    Args:
        override: Optional caller-selected effective instant.
    """

    override: datetime | None

    def now(self) -> datetime:
        """Read the clock at its original post-validation boundary.

        Returns:
            Original effective timestamp normalized to UTC.
        """
        return (self.override or legacy.datetime.now(UTC)).astimezone(UTC)


def _stages(effects: LegacySauvignon) -> SauvignonStages:
    return SauvignonStages(
        recommendation_seeds(),
        candidate_gathering(
            effects.lastfm, effects.cache_path, None, None, effects.progress
        ),
        AlbumGathering(effects, OptionalMessages(effects.progress)),
        AlbumEditionChoice(
            effects.choice_reader, legacy.CHOICE_SKIP, legacy.CHOICE_QUIT
        ),
    )


def sauvignon_workflow(
    spotify: Spotify,
    lastfm: legacy.LastFmReader,
    playlist_id: str,
    choice: legacy.AlbumChoiceReader | None,
    echo: legacy.Echo,
    progress: legacy.ProgressCallback | None,
    retry: legacy.RetryCall | None,
    export_path: Path,
    recent_path: Path,
    cache_path: Path,
    log_path: Path,
    now: datetime | None,
) -> SauvignonRun:
    """Construct one workflow with invocation-owned clients and callbacks.

    Args:
        spotify: Caller-owned Spotify client.
        lastfm: Caller-owned history source.
        playlist_id: Destination identity.
        choice: Edition interaction owned by this invocation.
        echo: Accepted-effect presenter.
        progress: Stage observer.
        retry: Retry policy configured after request validation.
        export_path: Canonical history location.
        recent_path: Recent history location.
        cache_path: Neighborhood cache location.
        log_path: Audit location.
        now: Optional UTC timestamp, observed after validation.

    Returns:
        A workflow whose construction performs no observations or effects.
    """
    from spotify_manager.infrastructure.recommendation_calendar import BerlinCalendar

    effects = LegacySauvignon(
        spotify,
        lastfm,
        playlist_id,
        choice,
        NoRetry(),
        export_path,
        recent_path,
        cache_path,
        log_path,
        progress,
        retry,
    )
    return SauvignonRun(
        effects,
        _stages(effects),
        SauvignonClock(now),
        BerlinCalendar(),
        OptionalMessages(progress),
        echo,
        legacy.DEFAULT_MAX_PLAYLIST_LENGTH,
        legacy.found_art.MIN_WEEKLY_CANDIDATE_POOL,
        legacy.found_art.WEEKLY_CANDIDATE_POOL_MULTIPLIER,
        legacy.MIN_SPOTIFY_CANDIDATES,
        legacy.SPOTIFY_CANDIDATE_MULTIPLIER,
    )
