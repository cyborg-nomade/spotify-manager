"""Capture original annual ranking, shallow state and retry reconciliation."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import new_wine
from spotify_manager.routines import new_year as legacy
from tests.support import new_year_run as support
from tests.support.new_year_run import FIXTURE
from tests.support.new_year_run import AnnualObservations
from tests.support.new_year_run import original_run
from tests.support.new_year_run import outcome


def ranking_inputs() -> list[list[Scrobble]]:
    """Build original timezone boundaries, blank parts and display spelling ties.

    Returns:
        Complete original ordered ranking profiles.
    """
    normal = _play("Alpha", "Track", "Album", "2025-06-01T12:00:00+02:00")
    profiles = [[], [normal], [normal, normal]]
    profiles.append([_play("Z", "B", "C", "2025-06-01T12:00:00+02:00"), normal])
    for when in (
        "2024-12-31T22:59:59+00:00",
        "2024-12-31T23:00:00+00:00",
        "2025-12-31T22:59:59+00:00",
        "2025-12-31T23:00:00+00:00",
    ):
        profiles.append([_play("Alpha", "Track", "Album", when)])
    for artist, track, album in (
        (" ", "Track", "Album"),
        ("Alpha", " ", "Album"),
        ("Alpha", "Track", " "),
        (" ALPHA ", " TRACK ", " ALBUM "),
        ("Álpha", "Track", "Album"),
    ):
        profiles.append(
            [_play(artist, track, album, "2025-06-01T12:00:00+02:00"), normal]
        )
    return profiles


def _play(artist: str, track: str, album: str, when: str) -> Scrobble:
    return Scrobble(
        track, artist, album, int(datetime.fromisoformat(when).timestamp() * 1000)
    )


def reconcile_outcome(
    top: bool, failure: str | None, automatic: bool, size: int
) -> object:
    """Observe original batch reconciliation, top placement and retry acceptance.

    Args:
        top: Original top-of-playlist placement.
        failure: Original before/after acceptance failure.
        automatic: Original caller automatic retry behavior.
        size: Original input population before duplicate requests.

    Returns:
        Complete original live membership and ordered effect prefix.
    """
    edge = AnnualObservations("normal", failure, automatic)
    edge.contents["destination"] = ["other", "uri-0", "uri-100"]
    uris = [f"uri-{index}" for index in range(size)] + ["uri-0", "uri-0"]
    result: dict[str, object] = {}
    try:
        with patch.object(new_wine, "load_playlist_tracks", edge.playlist):
            legacy._add_missing(
                cast(Spotify, edge), "destination", uris, edge.retry, top=top
            )
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result.update(trace=edge.trace, contents=edge.contents["destination"])
    return json.loads(json.dumps(result))


def cases(name: str) -> list[dict[str, object]]:
    """Read immutable original annual boundary observations.

    Args:
        name: Original fixture filename.

    Returns:
        Complete original inputs and observed outcomes.
    """
    return cast(
        list[dict[str, object]], json.loads(FIXTURE.with_name(name).read_text())
    )


def resumed_outcome(
    profile: str,
    preview: bool,
    run: Callable[
        [AnnualObservations, bool, int | None], dict[str, object]
    ] = original_run,
) -> object:
    """Observe original permissive resumed records and delayed native failure prefixes.

    Args:
        profile: Original stored-plan boundary shape.
        preview: Original preview behavior.
        run: Original or independently injected annual coordinator.

    Returns:
        Complete original outcome, native error and accepted live/durable effects.
    """
    edge = AnnualObservations("resume")
    _alter_run(edge, profile)
    result: dict[str, object] = {}
    try:
        result["result"] = run(edge, preview, 2025)
    except (RuntimeError, KeyError, TypeError, IndexError, AttributeError) as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result.update(trace=edge.trace, state=edge.state, contents=edge.contents)
    return json.loads(json.dumps(result))


def _alter_run(edge: AnnualObservations, profile: str) -> None:
    years = cast(dict[str, dict[str, object]], edge.state["years"])
    run = years["2025"]
    plan = cast(dict[str, object], run["plan"])
    run["completed"] = []
    if profile == "missing-completed":
        run.pop("completed")
    if profile == "missing-obsessions":
        plan.pop("obsessions")
    if profile == "missing-destinations":
        plan.pop("destinations")
    if profile == "empty-artists":
        plan["artists"] = []
    if profile == "stored-overrides":
        run.update(year=1999, dry_run=False, already_completed="retained")
    _alter_uri(run, plan, profile)


def _alter_uri(run: dict[str, object], plan: dict[str, object], profile: str) -> None:
    if profile not in {
        "missing-track-uri",
        "missing-artist-uri",
        "skipped-track-uri",
        "skipped-artist-uri",
    }:
        return
    kind = "tracks" if "track-uri" in profile else "artists"
    item = cast(list[dict[str, object]], plan[kind])[0]
    item.pop("uri")
    if profile.startswith("skipped"):
        run["completed"] = ["top tracks" if kind == "tracks" else "top artists"]


def large_outcome(
    preview: bool,
    run: Callable[
        [AnnualObservations, bool, int | None], dict[str, object]
    ] = original_run,
) -> object:
    """Observe original caps and a top artist whose marker lies outside the top fifty.

    Args:
        preview: Original preview behavior.
        run: Original or independently injected annual coordinator.

    Returns:
        Complete original capped plan, uncapped marker lookup and accepted effects.
    """
    with patch.object(support, "plays", _large_plays):
        return outcome("normal", preview, None, run=run)


def _large_plays() -> tuple[Scrobble, ...]:
    plays = []
    for artist in range(6):
        plays.extend(_repeated_artist_plays(artist))
    for index in range(201):
        plays.append(
            _play(
                "Zulu",
                f"Zulu {index:03}",
                f"Release {index:03}",
                "2025-06-01T12:00:00+02:00",
            )
        )
    return tuple(plays)


def _repeated_artist_plays(artist: int) -> list[Scrobble]:
    plays = []
    for track in range(11):
        play = _play(
            f"A{artist}",
            f"A{artist} Song {track:02}",
            f"A{artist} Release {track:02}",
            "2025-06-01T12:00:00+02:00",
        )
        plays.extend([play] * 10)
    return plays
