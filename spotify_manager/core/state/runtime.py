"""Runtime construction of the one process-wide state service."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.huggingface.state_store import HubStateStore
from spotify_manager.infrastructure.persistence.json_state_store import JsonStateStore


DEFAULT_STATE_REPO = "cyborg-nomade/spotify-manager-state"
DEFAULT_STATE_FILENAME = "state.json"
DEFAULT_LOCAL_STATE_PATH = (
    Path(__file__).resolve().parents[2] / "files" / DEFAULT_STATE_FILENAME
)


@lru_cache(maxsize=1)
def get_state_service() -> StateService:
    """Return the configured shared state service singleton."""
    backend = os.environ.get("SPOTIFY_MANAGER_STATE_BACKEND", "hub").casefold()
    if backend == "local":
        path = Path(
            os.environ.get(
                "SPOTIFY_MANAGER_STATE_LOCAL_PATH",
                str(DEFAULT_LOCAL_STATE_PATH),
            )
        )
        return StateService(JsonStateStore(path))
    if backend != "hub":
        raise StateConfigurationError(
            "SPOTIFY_MANAGER_STATE_BACKEND must be 'hub' or 'local'."
        )
    repo_id = os.environ.get("SPOTIFY_MANAGER_STATE_REPO", DEFAULT_STATE_REPO)
    filename = os.environ.get(
        "SPOTIFY_MANAGER_STATE_FILENAME",
        DEFAULT_STATE_FILENAME,
    )
    token = os.environ.get("SPOTIFY_MANAGER_STATE_TOKEN") or os.environ.get("HF_TOKEN")
    return StateService(HubStateStore(repo_id, filename=filename, token=token))


def reset_state_service() -> None:
    """Clear the runtime singleton after tests or configuration changes."""
    get_state_service.cache_clear()
