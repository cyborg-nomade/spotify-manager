"""Explicit state construction and the legacy process-wide service lifetime."""

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from spotify_manager.application.ports.state import StateStore
from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.huggingface.state_store import HubStateStore
from spotify_manager.infrastructure.persistence.json_state_store import JsonStateStore


DEFAULT_STATE_REPO = "cyborg-nomade/spotify-manager-state"
DEFAULT_STATE_FILENAME = "state.json"
DEFAULT_LOCAL_STATE_PATH = Path(__file__).resolve().parents[1] / "files/state.json"


def create_state_service(store: StateStore) -> StateService:
    """Compose the existing conflict-aware service with an explicit store.

    Args:
        store: Persistence dependency, including an in-memory implementation.

    Returns:
        An independent service with the original compare-and-swap semantics.
    """
    return StateService(store)


def configured_state_store(environment: Mapping[str, str]) -> StateStore:
    """Resolve persistence at the outer configuration boundary.

    Args:
        environment: Settings snapshot with the existing environment aliases.

    Returns:
        The configured local or Hugging Face adapter.

    Raises:
        StateConfigurationError: The backend is unsupported or misconfigured.
    """
    backend = environment.get("SPOTIFY_MANAGER_STATE_BACKEND", "hub").casefold()
    if backend == "local":
        path = environment.get("SPOTIFY_MANAGER_STATE_LOCAL_PATH")
        return JsonStateStore(
            Path(path) if path is not None else DEFAULT_LOCAL_STATE_PATH
        )
    if backend != "hub":
        raise StateConfigurationError(
            "SPOTIFY_MANAGER_STATE_BACKEND must be 'hub' or 'local'."
        )
    return HubStateStore(
        environment.get("SPOTIFY_MANAGER_STATE_REPO", DEFAULT_STATE_REPO),
        filename=environment.get(
            "SPOTIFY_MANAGER_STATE_FILENAME", DEFAULT_STATE_FILENAME
        ),
        token=environment.get("SPOTIFY_MANAGER_STATE_TOKEN")
        or environment.get("HF_TOKEN"),
    )


@lru_cache(maxsize=1)
def get_state_service() -> StateService:
    """Resolve and cache the legacy process service on first use.

    Returns:
        The process singleton, constructed without network reads.

    Raises:
        StateConfigurationError: The configured store cannot be constructed.
    """
    return create_state_service(configured_state_store(os.environ))


def reset_state_service() -> None:
    """Clear the process cache so the next call reads configuration again."""
    get_state_service.cache_clear()
