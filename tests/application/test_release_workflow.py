"""Exercise release checking independently against frozen original workflow outcomes."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.release_check_values import ReleaseCheckError
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.application.release_run import ReleaseRun
from tests.support.release_run import PROFILES
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


def _observe(profile: str, failure: str | None) -> dict[str, object]:
    context = opening(profile)
    effects = Effects(profile, failure, context.persisted_state)
    progress = ReleaseProgress(context, effects, "preview" in profile)
    outcome: object
    try:
        outcome = asdict(ReleaseRun(progress, "wine", "vintage", effects.choice).run())
    except (EffectFailureError, ReleaseCheckError) as exc:
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
def test_independent_release_workflow_contract(profile: str) -> None:
    """Keep every original complete-run scenario without an SDK or legacy runner.

    Args:
        profile: Frozen original workflow scenario.
    """
    assert _observe(profile, None) == _fixture()[profile]


@pytest.mark.parametrize("failure", FAILURES)
def test_independent_release_workflow_failure_prefix(failure: str) -> None:
    """Keep original accepted-effect and restart state prefixes on failures.

    Args:
        failure: Original accepted effect at which to stop.
    """
    assert _observe("album", failure) == _fixture()["failure:" + failure]


@pytest.mark.parametrize("preview", [False, True])
def test_release_cleanup_audit_follows_cleanup_progress(preview: bool) -> None:
    """Audit accepted Wine Cellar cleanup after its progress report.

    Args:
        preview: Preview or accepted cleanup mode.
    """
    context = opening("album")
    effects = Effects("duplicate_wine", persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, preview), "wine", "vintage", None
    ).run()
    assert summary.wine_cellar_duplicates_removed == 1
    cleanup = cast(list[object], effects.events[3])
    assert cleanup == [
        "progress",
        0,
        1,
        ("Would remove" if preview else "Removed")
        + " 1 duplicate Wine Cellar track(s)",
    ]
    audits = [
        event
        for event in effects.events
        if cast(list[object], event)[0] == "audit:wine_cellar_deduplicated"
    ]
    assert len(audits) == (0 if preview else 1)
    if not preview:
        assert effects.events[4] == [
            "audit:wine_cellar_deduplicated",
            "run",
            {"removed": 1, "retained": -1},
        ]


@pytest.mark.parametrize("profile", ["album", "pending", "destinations_full"])
def test_release_default_review_avoids_unnecessary_interaction(profile: str) -> None:
    """Use existing defaults without prompting when no reader or destination is needed.

    Args:
        profile: Missing reader, pending default or fully represented destinations.
    """
    context = opening(profile)
    effects = Effects(profile, persisted=context.persisted_state)
    reader = effects.choice if profile == "destinations_full" else None
    summary = ReleaseRun(
        ReleaseProgress(context, effects, False), "wine", "vintage", reader
    ).run()
    names = [cast(list[object], event)[0] for event in effects.events]
    assert "choice" not in names
    if profile == "pending":
        assert (
            summary.results[0].reason == "single kept pending for a future album or EP"
        )
        assert "release" in cast(ReleaseState, effects.persisted["pending_singles"])
    if profile == "destinations_full":
        assert summary.results[0].wine_cellar_action == "artist already present"


def test_preview_one_run_artist_skip_does_not_save_completion() -> None:
    """Keep interactive one-run skips out of preview restart state."""
    context = opening("skip")
    effects = Effects("skip", persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, True), "wine", "vintage", None
    ).run()
    assert summary.artists_processed == 1 and not effects.saves
    assert (
        cast(ReleaseState, effects.persisted["active_run"])["completed_artist_keys"]
        == []
    )


def test_release_processed_duplicate_is_not_recorded_again() -> None:
    """Keep terminal duplicate decisions out of subsequent review results."""
    context = opening("duplicates")
    cast(ReleaseState, context.state["processed_releases"])["b"] = {"accepted": True}
    effects = Effects("duplicates", persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, False), "wine", "vintage", None
    ).run()
    assert [result.release_id for result in summary.results] == ["c", "a"]


@pytest.mark.parametrize("profile", ["other_pending", "processed"])
def test_release_invalid_or_other_artist_pending_records_are_ignored(
    profile: str,
) -> None:
    """Only decoded pending markers owned by the current artist can reopen a release.

    Args:
        profile: Other-artist or malformed pending record.
    """
    context = opening("pending_processed")
    if profile == "processed":
        cast(ReleaseState, context.state["pending_singles"])["release"] = None
    effects = Effects(profile, persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, False), "wine", "vintage", None
    ).run()
    assert summary.results == ()


def test_release_pending_absent_from_catalog_reuses_retained_track() -> None:
    """Reconsider an existing pending single even when the live catalog is empty."""
    context = opening("pending_processed")
    effects = Effects("catalog_empty", persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, False), "wine", "vintage", None
    ).run()
    assert summary.results[0].release_id == "release"
    assert summary.results[0].first_track_id == "track"
    assert not any(cast(list[object], event)[0] == "first" for event in effects.events)


def test_release_unplayable_single_is_terminal_without_record_matching() -> None:
    """Skip review prompts and playlist writes for unplayable singles."""
    context = opening("pending")
    effects = Effects("empty_single", persisted=context.persisted_state)
    summary = ReleaseRun(
        ReleaseProgress(context, effects, False), "wine", "vintage", None
    ).run()
    assert summary.results[0].reason == "release has no playable first track"
    assert not any(
        str(cast(list[object], event)[0]).startswith("add:") for event in effects.events
    )
