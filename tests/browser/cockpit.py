"""Serve cockpit pages and process-local state for browser review."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse

from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.state.editor import state_editor_schema
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.interfaces.http.models.common import LibraryMirrorFilesStatus
from spotify_manager.interfaces.http.models.common import ServerFileStatus
from spotify_manager.interfaces.http.models.flush_mode import FlushControlRequest
from spotify_manager.interfaces.http.models.flush_mode import FlushModeStatus
from spotify_manager.interfaces.http.models.state import (
    SharedStateNamespaceReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import SharedStateReplaceRequest
from spotify_manager.interfaces.http.models.state import SharedStateSnapshot
from spotify_manager.interfaces.http.models.state import SharedStateSummary


FRONTEND = Path(__file__).resolve().parents[2] / "spotify_manager" / "frontend"
PUBLISHED_AT = "2024-10-31T08:14:00Z"
router = APIRouter()


def _initial_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "created_at": PUBLISHED_AT,
        "updated_at": PUBLISHED_AT,
        "namespaces": {
            "discography": {
                "updated_at": PUBLISHED_AT,
                "value": {"version": 1, "next_queue": "newfoundland"},
            },
        },
    }


@dataclass
class CockpitFixture:
    """Keep the synthetic publication and Flush Mode in process memory."""

    control: FlushControl = "automatic"
    revision: int = 1
    document: dict[str, object] = field(default_factory=_initial_document)


_cockpit = CockpitFixture()


def reset_cockpit() -> None:
    """Restore the initial synthetic cockpit state."""
    global _cockpit
    _cockpit = CockpitFixture()


@router.get("/")
def cockpit_shell() -> FileResponse:
    """Serve the real cockpit HTML."""
    return FileResponse(FRONTEND / "index.html")


@router.get("/genre-reveal")
def genre_shell() -> FileResponse:
    """Serve the real Genre Reveal HTML."""
    return FileResponse(FRONTEND / "genre-reveal.html")


@router.get("/library-mirrors/status")
async def mirror_status() -> LibraryMirrorFilesStatus:
    """Describe the four sample sources displayed on the signal board."""
    return LibraryMirrorFilesStatus(
        files=[
            ServerFileStatus(filename=name, exists=True, updated_at=PUBLISHED_AT)
            for name in ARTIFACT_FILENAMES.values()
        ],
    )


def _attachment(document: object, filename: str) -> JSONResponse:
    return JSONResponse(
        document, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/flush-mode")
@router.post("/flush-mode/check")
async def flush_status() -> FlushModeStatus:
    """Observe the effective override against the same sample queue counts."""
    return FlushModeStatus(
        control=_cockpit.control,
        active=_cockpit.control == "on",
        automatic_active=False,
        queue_tracks=38,
        queue_2_tracks=24,
        checked_at=PUBLISHED_AT,
        attempted_at=PUBLISHED_AT,
        error=None,
        reason="Sample queue counts are below the automatic trigger.",
    )


@router.put("/flush-mode/control")
async def set_flush_control(update: FlushControlRequest) -> FlushModeStatus:
    """Change the override only for this process.

    Args:
        update: The selected Flush Mode control.

    Returns:
        Updated status using the sample queue counts.
    """
    _cockpit.control = update.control
    return await flush_status()


def _revision() -> str:
    return f"sample-revision-{_cockpit.revision}"


@router.get("/state")
async def state_snapshot() -> SharedStateSnapshot:
    """Return a detached copy of the sample document and its revision."""
    return SharedStateSnapshot(
        revision=_revision(), document=deepcopy(_cockpit.document)
    )


@router.get("/state/summary")
async def state_summary() -> SharedStateSummary:
    """Show the sample state's revision and publication timestamp."""
    namespaces = _cockpit.document.get("namespaces")
    names = (
        dict.fromkeys(namespaces, PUBLISHED_AT) if isinstance(namespaces, dict) else {}
    )
    return SharedStateSummary(
        revision=_revision(), updated_at=PUBLISHED_AT, namespaces=names
    )


@router.get("/state/schema")
async def editor_schema() -> dict[str, object]:
    """Use the production editor metadata with the sample document."""
    return state_editor_schema()


@router.get("/state/export")
async def export_state() -> JSONResponse:
    """Download only the synthetic shared state."""
    return _attachment(_cockpit.document, "spotify-manager-state.json")


def _check_revision(expected: str) -> None:
    if expected != _revision():
        raise HTTPException(409, "Sample state changed since it was opened.")


@router.put("/state")
async def replace_state(update: SharedStateReplaceRequest) -> SharedStateSnapshot:
    """Replace the process-local sample document after a revision check.

    Args:
        update: Proposed document and observed revision.

    Returns:
        The saved fixture document and next revision.

    Raises:
        HTTPException: The sample revision has already changed.
    """
    _check_revision(update.expected_revision)
    _cockpit.document = update.document
    _cockpit.revision += 1
    return await state_snapshot()


@router.put("/state/namespaces/{namespace}")
async def replace_namespace(
    namespace: str, update: SharedStateNamespaceReplaceRequest
) -> SharedStateSnapshot:
    """Replace a sample namespace after a revision check.

    Args:
        namespace: Name of the selected sample namespace.
        update: Proposed namespace value and observed revision.

    Returns:
        The saved fixture document and next revision.

    Raises:
        HTTPException: The revision changed or the namespace is absent.
    """
    _check_revision(update.expected_revision)
    namespaces = _cockpit.document.get("namespaces")
    if not isinstance(namespaces, dict) or namespace not in namespaces:
        raise HTTPException(404, "Unknown sample namespace.")
    namespaces[namespace] = {"value": update.value, "updated_at": PUBLISHED_AT}
    _cockpit.revision += 1
    return await state_snapshot()
