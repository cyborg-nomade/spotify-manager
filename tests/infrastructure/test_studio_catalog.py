"""Shared studio track failures retain each routine's original error translation."""

from collections.abc import Callable
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.requeue_result import RequeueForADreamError
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.legacy.queue_3 import LegacyQueue3Catalog
from spotify_manager.infrastructure.legacy.spotify import SpotifyRequeueCatalog
from spotify_manager.infrastructure.legacy.studio_catalog import StudioCatalogAccess
from spotify_manager.routines import new_wine
from tests.support.listening_values import studio_release


def _retry(operation: Callable[[], object], _description: str) -> object:
    return operation()


def _failed_tracks(
    client: Spotify,
    release: ReleaseCandidate,
    retry: RetryCall,
) -> tuple[ReleaseTrack, ...]:
    raise new_wine.NewWineError("tracks unavailable")


def _reader(consumer: str) -> Callable[[DiscographyRelease], tuple[ReleaseTrack, ...]]:
    client = cast(Spotify, object())
    if consumer == "shared":
        return StudioCatalogAccess(client, _retry).tracks
    if consumer == "queue3":
        return LegacyQueue3Catalog(client, _retry, {}).tracks
    return SpotifyRequeueCatalog(client, _retry).release_tracks


@pytest.mark.parametrize(
    "consumer,error_type",
    [
        ("shared", SlowListeningError),
        ("queue3", SlowListeningError),
        ("requeue", RequeueForADreamError),
    ],
)
def test_shared_track_error_retains_message_and_cause_chain(
    monkeypatch: pytest.MonkeyPatch,
    consumer: str,
    error_type: type[Exception],
) -> None:
    """Shared observations preserve the deliberately different public error types.

    Args:
        monkeypatch: Scoped parsed-track boundary substitution.
        consumer: Original shared catalog consumer.
        error_type: Expected outer routine error type.
    """
    monkeypatch.setattr(new_wine, "load_release_tracks", _failed_tracks)
    with pytest.raises(error_type, match="tracks unavailable") as error:
        _reader(consumer)(studio_release("album", "Album"))
    cause = error.value.__cause__
    if consumer == "requeue":
        assert isinstance(cause, SlowListeningError)
        cause = cause.__cause__
    assert isinstance(cause, new_wine.NewWineError)
