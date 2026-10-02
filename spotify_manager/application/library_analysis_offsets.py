"""Monotonic saved-resource scans and bounded recent-addition reconciliation."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Literal
from typing import cast

from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.application.library_analysis_values import ResourceState
from spotify_manager.domain.library_analysis import deduplicate_models
from spotify_manager.domain.library_analysis_values import ALBUM_PAGE_LIMIT
from spotify_manager.domain.library_analysis_values import (
    OFFSET_RECONCILIATION_STABLE_PAGES,
)
from spotify_manager.domain.library_analysis_values import RECONCILIATION_STABLE_PASSES
from spotify_manager.domain.library_analysis_values import TRACK_PAGE_LIMIT
from spotify_manager.domain.library_analysis_values import IncompleteLiveResourceError
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryTrack


type OffsetResource = Literal["albums", "tracks"]


@dataclass(frozen=True)
class OffsetScan:
    """Bind one original selected method and resource-specific page rules.

    Args:
        resource: Original saved album or track resource.
        read: Original selected live method.
        convert: Original tolerant saved-item conversion.
        limit: Original page size.
        stable_pages: Original consecutive unchanged-page bound.
    """

    resource: OffsetResource
    read: OffsetRead
    convert: Callable[[object], LibraryModel | None]
    limit: int
    stable_pages: int


def offset_scan(
    session: AnalysisSession, resource: OffsetResource, initial: bool
) -> OffsetScan:
    """Select the original live method after the initial checkpoint boundary.

    Args:
        session: Original mutable analysis invocation.
        resource: Original saved-resource identity.
        initial: Whether this is the monotonic initial scan.

    Returns:
        Original resource-specific live reader and limits.
    """
    method = session.catalog.offset(resource, initial)
    converter = session.catalog.album if resource == "albums" else session.catalog.track
    limit = ALBUM_PAGE_LIMIT if resource == "albums" else TRACK_PAGE_LIMIT
    return OffsetScan(
        resource, method, converter, limit, OFFSET_RECONCILIATION_STABLE_PAGES[resource]
    )


def converted_items(
    rows: list[object], converter: Callable[[object], LibraryModel | None]
) -> list[LibraryModel]:
    """Retain valid original rows, including duplicate new identities within a page.

    Args:
        rows: Original complete raw page in encounter order.
        converter: Original tolerant row parser.

    Returns:
        Original accepted models in row order.
    """
    converted: list[LibraryModel] = []
    for raw in rows:
        item = converter(raw)
        if item is not None:
            converted.append(item)
    return converted


def staged_offset(
    session: AnalysisSession, resource: OffsetResource
) -> list[LibraryModel]:
    """Read original staged saved-resource facts.

    Args:
        session: Original analysis invocation.
        resource: Original saved-resource identity.

    Returns:
        Original complete staged rows.
    """
    if resource == "albums":
        return list(
            session.files.staged(session.paths.stage(resource), YourLibraryAlbum)
        )
    return list(session.files.staged(session.paths.stage(resource), YourLibraryTrack))


def reported_total(page: dict[str, object]) -> int | None:
    """Retain original integer totals, including booleans accepted as integers.

    Args:
        page: Original validated page envelope.

    Returns:
        Original optional integer total.
    """
    value = page.get("total")
    return value if isinstance(value, int) else None


def scan_initial(session: AnalysisSession, resource: OffsetResource) -> None:
    """Scan original offsets monotonically before beginning reconciliation.

    Args:
        session: Original analysis invocation.
        resource: Original saved-resource identity.
    """
    state = session.checkpoint["resources"][resource]
    if state["status"] not in {"pending", "scanning"}:
        return
    state["status"] = "scanning"
    session.save()
    scan = offset_scan(session, resource, True)
    while True:
        page, rows = _save_initial_page(session, scan, state)
        if not rows and page.get("next"):
            raise IncompleteLiveResourceError(
                f"Spotify returned an empty {resource} page with a next link."
            )
        if not rows or not page.get("next"):
            state["status"] = "reconciling"
            state["stable_passes"] = 0
            session.save()
            return


def _save_initial_page(
    session: AnalysisSession, scan: OffsetScan, state: ResourceState
) -> tuple[dict[str, object], list[object]]:
    session.check_cancel()
    offset = int(state["offset"])
    page = session.request(
        partial(scan.read, limit=scan.limit, offset=offset),
        f"reading saved {scan.resource} at offset {offset}",
    )
    rows = session.catalog.items(page, scan.resource)
    converted = converted_items(rows, scan.convert)
    session.files.append(session.paths.stage(scan.resource), converted)
    state["skipped"] += len(rows) - len(converted)
    state["offset"] = offset + len(rows)
    state["pages"] += 1
    envelope = cast(dict[str, object], page)
    state["total"] = envelope.get("total")
    session.save()
    session.event(
        "page_saved",
        resource=scan.resource,
        offset=offset,
        count=len(converted),
        reported_total=envelope.get("total"),
    )
    session.notify(
        scan.resource,
        int(state["offset"]),
        reported_total(envelope),
        "Reading live API",
    )
    return envelope, rows


def reconcile(session: AnalysisSession, resource: OffsetResource) -> None:
    """Stop after two complete recent-edge passes find no additions.

    Args:
        session: Original analysis invocation.
        resource: Original saved-resource identity.
    """
    state = session.checkpoint["resources"][resource]
    if state["status"] == "complete":
        count = len(deduplicate_models(staged_offset(session, resource)))
        session.notify(resource, count, count, "Complete")
        return
    scan = offset_scan(session, resource, False)
    while int(state["stable_passes"]) < RECONCILIATION_STABLE_PASSES:
        added = _reconcile_pass(session, scan, state)
        finish_pass(session, resource, state, added)
    complete_resource(session, resource, partial(staged_offset, session, resource))


def _reconcile_pass(
    session: AnalysisSession, scan: OffsetScan, state: ResourceState
) -> int:
    known = {item.spotify_id for item in staged_offset(session, scan.resource)}
    offset = 0
    added = 0
    stable_pages = 0
    while True:
        rows, page, unseen = _reconcile_page(session, scan, state, known, offset)
        added += unseen
        stable_pages = 0 if unseen else stable_pages + 1
        if not rows or not page.get("next") or stable_pages >= scan.stable_pages:
            return added
        offset += len(rows)


def _reconcile_page(
    session: AnalysisSession,
    scan: OffsetScan,
    state: ResourceState,
    known: set[str],
    offset: int,
) -> tuple[list[object], dict[str, object], int]:
    session.check_cancel()
    page = session.request(
        partial(scan.read, limit=scan.limit, offset=offset),
        f"reconciling saved {scan.resource} at offset {offset}",
    )
    rows = session.catalog.items(page, scan.resource)
    unseen = unseen_items(converted_items(rows, scan.convert), known)
    session.files.append(session.paths.stage(scan.resource), unseen)
    known.update(item.spotify_id for item in unseen)
    session.save()
    envelope = cast(dict[str, object], page)
    label = f"Checking for additions (pass {int(state['stable_passes']) + 1})"
    session.notify(scan.resource, len(known), reported_total(envelope), label)
    return rows, envelope, len(unseen)


def unseen_items(items: list[LibraryModel], known: set[str]) -> list[LibraryModel]:
    """Compare the entire page against the original pre-page identity snapshot.

    Args:
        items: Original converted page rows, including duplicate identities.
        known: Original identities accepted before this page.

    Returns:
        Original unseen rows, retaining within-page duplicates.
    """
    return [item for item in items if item.spotify_id not in known]


def finish_pass(
    session: AnalysisSession, resource: ResourceName, state: ResourceState, added: int
) -> None:
    """Persist original stable-pass progress after its optional additions audit.

    Args:
        session: Original analysis invocation.
        resource: Original active resource.
        state: Original mutable resource progress.
        added: Original accepted row count for this pass.
    """
    if added:
        state["stable_passes"] = 0
        session.event("reconciliation_additions", resource=resource, count=added)
    else:
        state["stable_passes"] += 1
    session.save()


def complete_resource(
    session: AnalysisSession,
    resource: ResourceName,
    read: Callable[[], list[LibraryModel]],
) -> None:
    """Publish original resource completion after its final checkpoint.

    Args:
        session: Original analysis invocation.
        resource: Original completed resource.
        read: Original staged read after the completion checkpoint is accepted.
    """
    state = session.checkpoint["resources"][resource]
    state["status"] = "complete"
    session.save()
    count = len(deduplicate_models(read()))
    session.event(
        "resource_completed", resource=resource, count=count, skipped=state["skipped"]
    )
    session.notify(resource, count, count, "Complete")


def seed_incremental(session: AnalysisSession, resource: OffsetResource) -> None:
    """Retain stored rows until an explicitly requested full rebuild.

    Args:
        session: Original analysis invocation.
        resource: Original saved-resource identity.
    """
    state = session.checkpoint["resources"][resource]
    if state["status"] != "pending":
        return
    if resource == "albums":
        existing: list[LibraryModel] = list(
            session.files.models(session.paths.albums_total, YourLibraryAlbum)
        )
        retained_label = "Unsaved albums"
    else:
        existing = list(
            session.files.models(session.paths.liked_tracks_total, YourLibraryTrack)
        )
        retained_label = "Unliked tracks"
    session.files.append(session.paths.stage(resource), existing)
    state["status"] = "reconciling"
    state["total"] = len(existing)
    state["stable_passes"] = 0
    session.save()
    session.event(f"incremental_{resource}_seeded", count=len(existing))
    session.echo(
        f"{resource.title()}: checking recent additions against "
        f"{len(existing)} stored entries. {retained_label} remain until a full rebuild."
    )
    session.notify(resource, len(existing), len(existing), "Checking recent additions")
