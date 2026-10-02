"""Bind original deployment environment and frontend paths at startup."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebEnvironment:
    """Retain original deployment password, token and local bypass settings.

    Args:
        password: Original gate password or disabled configuration.
        automation_token: Original automation credential or none.
        allow_loopback: Original local development qualification.
    """

    password: str | None
    automation_token: str | None
    allow_loopback: bool


def environment() -> WebEnvironment:
    """Read original deployment settings and emit the original disabled-gate warning.

    Returns:
        Explicit deployment configuration with unchanged falsey handling.
    """
    password = os.environ.get("APP_PASSWORD") or None
    token = os.environ.get("AUTOMATION_TOKEN") or None
    local = not any(os.environ.get(name) for name in ("SPACE_ID", "SPACE_HOST"))
    if password is None:
        logging.getLogger("uvicorn.error").warning(
            "APP_PASSWORD is not set — the password gate is DISABLED. "
            "Set APP_PASSWORD before deploying."
        )
    return WebEnvironment(password, token, local)


def managed_path(name: str, default: Path) -> Path:
    """Retain original environment path overrides, including empty strings.

    Args:
        name: Original environment variable.
        default: Original routine path fallback.

    Returns:
        Original configured managed path.
    """
    return Path(os.environ.get(name, default))
