"""Serve only the data-free Spotify Manager cockpit shell and its assets."""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from spotify_manager.domain.web_access import COCKPIT_ASSETS


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def cockpit_shell() -> FileResponse:
    """Return the standalone shell with browser cache revalidation."""
    return FileResponse(
        FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"}
    )


def cockpit_asset(filename: str) -> FileResponse:
    """Return one exact packaged asset using browser cache revalidation.

    Args:
        filename: A basename from the cockpit's public static asset list.

    Returns:
        The requested static asset.

    Raises:
        HTTPException: The requested basename is outside the allowlist.
    """
    if filename not in COCKPIT_ASSETS:
        raise HTTPException(404, "Unknown cockpit asset.")
    return FileResponse(
        FRONTEND_DIR / "cockpit-assets" / filename,
        headers={"Cache-Control": "no-cache"},
    )
