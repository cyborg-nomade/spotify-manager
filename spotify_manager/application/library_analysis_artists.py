"""Cursor discovery, stable artist reconciliation and resumable live verification."""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_offsets import complete_resource
from spotify_manager.application.library_analysis_offsets import converted_items
from spotify_manager.application.library_analysis_offsets import finish_pass
from spotify_manager.application.library_analysis_offsets import reported_total
from spotify_manager.application.library_analysis_offsets import unseen_items
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.application.library_analysis_values import ResourceState
from spotify_manager.domain.library_analysis import deduplicate_models
from spotify_manager.domain.library_analysis import verification_candidates
from spotify_manager.domain.library_analysis_values import ARTIST_DIRECT_MAX_PAGES
from spotify_manager.domain.library_analysis_values import (
    ARTIST_VERIFICATION_BATCH_LIMIT,
)
from spotify_manager.domain.library_analysis_values import (
    ARTIST_VERIFICATION_MAX_ATTEMPTS,
)
from spotify_manager.domain.library_analysis_values import RECONCILIATION_STABLE_PASSES
from spotify_manager.domain.library_analysis_values import IncompleteLiveResourceError
from spotify_manager.domain.library_analysis_values import (
    _FollowedArtistsEndpointUnavailableError,
)
from spotify_manager.models.your_library import YourLibraryArtist


def candidate_path(session: AnalysisSession) -> Path:
    """Locate the original resumable artist candidate stream.

    Args:
        session: Original independent artist workspace.

    Returns:
        Original candidate staging file.
    """
    return session.paths.staging_dir / "artist_candidates.jsonl"


async def staged_artists(session: AnalysisSession) -> list[LibraryModel]:
    """Read complete original artist staging facts.

    Args:
        session: Original analysis invocation.

    Returns:
        Original staged artists in encounter order.
    """
    return list(
        await session.files.staged(session.paths.stage("artists"), YourLibraryArtist)
    )


async def artist_count(session: AnalysisSession) -> int:
    """Read the original deduplicated staged artist count.

    Args:
        session: Original analysis invocation.

    Returns:
        Original newest-value identity count.
    """
    return len(deduplicate_models(await staged_artists(session)))


async def scan_initial(session: AnalysisSession) -> None:
    """Scan original cursor pages once with a bounded direct endpoint budget.

    Args:
        session: Original mutable analysis invocation.

    Raises:
        _FollowedArtistsEndpointUnavailableError: Original direct budget is exhausted.
        IncompleteLiveResourceError: Original cursor does not advance.
    """
    state = session.checkpoint["resources"]["artists"]
    if state["status"] not in {"pending", "scanning"}:
        return
    state["status"] = "scanning"
    await session.save()
    while True:
        session.check_cancel()
        if int(state["pages"]) >= ARTIST_DIRECT_MAX_PAGES:
            raise _FollowedArtistsEndpointUnavailableError(
                "the followed-artists cursor scan reached its bounded page budget"
            )
        after = state["after"]
        rows, page, next_after = await _save_initial_page(session, state, after)
        if not rows or not page.get("next"):
            await _begin_reconciliation(session, state)
            return
        check_cursor(next_after, after)


async def _save_initial_page(
    session: AnalysisSession, state: ResourceState, after: str | None
) -> tuple[list[object], dict[str, object], str | None]:
    for attempt in session.request.attempts(
        f"reading followed artists after {after or 'the beginning'}"
    ):
        async with attempt:
            response = await session.catalog.artists(after)
    rows, page = session.catalog.artist_items(response)
    converted = converted_items(rows, session.catalog, "artists")
    await session.files.append(session.paths.stage("artists"), converted)
    state["skipped"] += len(rows) - len(converted)
    state["pages"] += 1
    state["total"] = page.get("total")
    cursors = cast(dict[str, object], page.get("cursors") or {})
    next_after = cast(str | None, cursors.get("after"))
    state["after"] = next_after
    await session.save()
    if session.progress:
        session.progress.progress(
            "artists",
            (await artist_count(session)),
            reported_total(page),
            "Reading live API",
        )
    return rows, page, next_after


async def _begin_reconciliation(session: AnalysisSession, state: ResourceState) -> None:
    state["status"] = "reconciling"
    state["stable_passes"] = 0
    state["after"] = None
    await session.save()


def check_cursor(next_after: str | None, after: str | None) -> None:
    """Preserve original native cursor equality and advancement checks.

    Args:
        next_after: Original returned raw cursor.
        after: Original requested cursor.

    Raises:
        IncompleteLiveResourceError: Original cursor is absent or unchanged.
    """
    if next_after is None or next_after == after:
        raise IncompleteLiveResourceError(
            "Spotify did not advance the followed-artists cursor."
        )


async def reconcile(session: AnalysisSession) -> None:
    """Require two complete cursor passes without new artist rows.

    Args:
        session: Original analysis invocation.
    """
    state = session.checkpoint["resources"]["artists"]
    if state["status"] == "complete":
        count = await artist_count(session)
        session.notify("artists", count, count, "Complete")
        return
    while int(state["stable_passes"]) < RECONCILIATION_STABLE_PASSES:
        added = await _reconcile_pass(session, state)
        await finish_pass(session, "artists", state, added)
    await complete_resource(session, "artists")


async def _reconcile_pass(session: AnalysisSession, state: ResourceState) -> int:
    known = {item.spotify_id for item in (await staged_artists(session))}
    after: str | None = None
    added = 0
    while True:
        rows, page, unseen = await _reconcile_page(session, state, known, after)
        added += unseen
        cursors = cast(dict[str, object], page.get("cursors") or {})
        next_after = cast(str | None, cursors.get("after"))
        if not rows or not page.get("next"):
            return added
        check_cursor(next_after, after)
        after = str(next_after)


async def _reconcile_page(
    session: AnalysisSession, state: ResourceState, known: set[str], after: str | None
) -> tuple[list[object], dict[str, object], int]:
    session.check_cancel()
    for attempt in session.request.attempts(
        f"reconciling followed artists after {after or 'the beginning'}"
    ):
        async with attempt:
            response = await session.catalog.reconcile_artists(after)
    rows, page = session.catalog.artist_items(response)
    converted = converted_items(rows, session.catalog, "artists")
    unseen = unseen_items(converted, known)
    await session.files.append(session.paths.stage("artists"), unseen)
    known.update(item.spotify_id for item in unseen)
    await session.save()
    label = f"Checking for additions (pass {int(state['stable_passes']) + 1})"
    session.notify("artists", len(known), reported_total(page), label)
    return rows, page, len(unseen)


async def prepare_verification(
    session: AnalysisSession,
    *,
    full_rebuild: bool,
    reason: str,
) -> None:
    """Stage original fallback candidates after observing original source priority.

    Args:
        session: Original artist analysis invocation.
        full_rebuild: Original retain-versus-verify-all choice.
        reason: Original visible fallback explanation.
    """
    state = session.checkpoint["resources"]["artists"]
    if state["status"] == "verifying_fallback":
        return
    existing = await session.files.models(
        session.paths.artists_total, YourLibraryArtist
    )
    partial_live = await session.files.staged(
        session.paths.stage("artists"), YourLibraryArtist
    )
    export_artists = await session.files.export_artists(session.paths)
    candidates, retained = verification_candidates(
        existing, export_artists, partial_live, full_rebuild
    )
    await _stage_verification(session, candidates, retained, full_rebuild, reason)


async def _stage_verification(
    session: AnalysisSession,
    candidates: list[YourLibraryArtist],
    retained: list[YourLibraryArtist],
    full_rebuild: bool,
    reason: str,
) -> None:
    await session.files.remove(candidate_path(session))
    await session.files.remove(session.paths.stage("artists"))
    await session.files.append(candidate_path(session), candidates)
    await session.files.append(session.paths.stage("artists"), retained)
    state = session.checkpoint["resources"]["artists"]
    state.update(
        {
            "status": "verifying_fallback",
            "candidate_index": 0,
            "retained": len(retained),
            "total": len(retained) + len(candidates),
            "source": "live_verified_fallback",
            "after": None,
        }
    )
    await session.save()
    await session.event(
        "artist_fallback_activated",
        reason=reason,
        full_rebuild=full_rebuild,
        retained=len(retained),
        candidates=len(candidates),
    )
    session.output.echo(
        f"Artists: {reason}; checking {len(candidates)} candidate(s) through "
        "Spotify's live follow-status endpoint."
    )


async def verify(session: AnalysisSession) -> None:
    """Verify candidate batches with durable offsets and the original truthiness rule.

    Args:
        session: Original independent artist analysis invocation.
    """
    state = session.checkpoint["resources"]["artists"]
    candidates = await session.files.staged(candidate_path(session), YourLibraryArtist)
    retained = int(state.get("retained", 0))
    while int(state.get("candidate_index", 0)) < len(candidates):
        await _verify_batch(session, state, candidates, retained)
    state["status"] = "complete"
    await session.save()
    if session.progress:
        count = await artist_count(session)
        session.progress.progress("artists", count, count, "Complete")


async def _verify_batch(
    session: AnalysisSession,
    state: ResourceState,
    candidates: list[YourLibraryArtist],
    retained: int,
) -> None:
    session.check_cancel()
    start = int(state.get("candidate_index", 0))
    batch = candidates[start : start + ARTIST_VERIFICATION_BATCH_LIMIT]
    identities = [item.spotify_id for item in batch]
    for attempt in session.request.attempts(
        f"verifying followed artists {start + 1}-{start + len(batch)}",
        max_attempts=ARTIST_VERIFICATION_MAX_ATTEMPTS,
    ):
        async with attempt:
            response = await session.catalog.following(identities)
    followed = _followed_candidates(batch, response)
    await session.files.append(session.paths.stage("artists"), followed)
    state["candidate_index"] = start + len(batch)
    state["skipped"] += len(batch) - len(followed)
    await session.save()
    await session.event(
        "artist_candidates_verified",
        start=start,
        checked=len(batch),
        followed=len(followed),
    )
    session.notify(
        "artists",
        retained + int(state["candidate_index"]),
        int(cast(int, state["total"])),
        "Verifying live follow status",
    )


def _followed_candidates(
    batch: list[YourLibraryArtist], response: object
) -> list[YourLibraryArtist]:
    statuses = list(response) if isinstance(response, Sequence) else []
    if len(statuses) != len(batch):
        raise IncompleteLiveResourceError(
            "Spotify returned an incomplete artist-follow verification batch."
        )
    followed: list[YourLibraryArtist] = []
    for artist, is_followed in zip(batch, statuses, strict=True):
        if is_followed:
            followed.append(artist)
    return followed
