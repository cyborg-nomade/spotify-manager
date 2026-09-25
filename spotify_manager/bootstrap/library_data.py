"""Outer composition and managed-path helpers for shared library data."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from spotify_manager.application.ports.mirrors import LibraryDataStore
from spotify_manager.core.library_data.models import ALL_ARTIFACTS
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataError
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.huggingface.library_data_store import (
    HubLibraryDataStore,
)
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)


DEFAULT_LIBRARY_DATA_REPO = "cyborg-nomade/spotify-manager-data"
DEFAULT_LIBRARY_DATA_MANIFEST = "manifest.json"
FILES_DIR = Path(__file__).resolve().parents[1] / "files"
DEFAULT_LIBRARY_DATA_LOCAL_ROOT = FILES_DIR / "library_data_store"
DEFAULT_ARTIFACT_PATHS: dict[ArtifactName, Path] = {
    "albums": FILES_DIR / "albums_total_new.json",
    "tracks": FILES_DIR / "liked_tracks_total.json",
    "artists": FILES_DIR / "artists_total.json",
    "scrobbles": FILES_DIR / "lastfmstats-man-et-arms.json",
}
_PATH_TO_ARTIFACT = {
    path.resolve(): name for name, path in DEFAULT_ARTIFACT_PATHS.items()
}
_logger = logging.getLogger(__name__)


def create_library_data_service(
    store: LibraryDataStore,
    paths: dict[ArtifactName, Path],
) -> LibraryDataService:
    """Compose integrity and conflict handling with explicit persistence.

    Args:
        store: Durable manifest and artifact storage.
        paths: Working paths for the four canonical artifacts.

    Returns:
        An independent service retaining the existing integrity checks.

    Raises:
        ValueError: A canonical artifact path is missing.
    """
    return LibraryDataService(store, paths)


def configured_library_store(environment: Mapping[str, str]) -> LibraryDataStore:
    """Select the original adapter using the existing environment aliases.

    Args:
        environment: Configuration snapshot supplied by the outer runtime.

    Returns:
        A local or Hugging Face library adapter.

    Raises:
        LibraryDataConfigurationError: The backend is unsupported or misconfigured.
    """
    backend = environment.get("SPOTIFY_MANAGER_DATA_BACKEND", "hub").casefold()
    manifest = environment.get(
        "SPOTIFY_MANAGER_DATA_MANIFEST", DEFAULT_LIBRARY_DATA_MANIFEST
    )
    if backend == "local":
        root = environment.get("SPOTIFY_MANAGER_DATA_LOCAL_ROOT")
        path = Path(root) if root is not None else DEFAULT_LIBRARY_DATA_LOCAL_ROOT
        return JsonLibraryDataStore(path, manifest_filename=manifest)
    if backend != "hub":
        raise LibraryDataConfigurationError(
            "SPOTIFY_MANAGER_DATA_BACKEND must be 'hub' or 'local'."
        )
    token = environment.get("SPOTIFY_MANAGER_DATA_TOKEN")
    token = (
        token
        or environment.get("SPOTIFY_MANAGER_STATE_TOKEN")
        or environment.get("HF_TOKEN")
    )
    return HubLibraryDataStore(
        environment.get("SPOTIFY_MANAGER_DATA_REPO", DEFAULT_LIBRARY_DATA_REPO),
        manifest_filename=manifest,
        token=token,
    )


@lru_cache(maxsize=1)
def get_library_data_service() -> LibraryDataService:
    """Construct the legacy process singleton on first use.

    Returns:
        The original library service with its configured store and paths.

    Raises:
        LibraryDataConfigurationError: The configured backend is invalid.
    """
    return create_library_data_service(
        configured_library_store(os.environ), DEFAULT_ARTIFACT_PATHS
    )


def reset_library_data_service() -> None:
    """Clear the cache so the next call reads configuration again."""
    get_library_data_service.cache_clear()


def artifact_for_path(path: Path) -> ArtifactName | None:
    """Look up a canonical managed path.

    Args:
        path: Candidate working path.

    Returns:
        The artifact name, or None for an unmanaged path.
    """
    return _PATH_TO_ARTIFACT.get(path.resolve())


def publish_managed_path(path: Path, *, source: str) -> bool:
    """Publish a managed path through the original integrity-aware service.

    Args:
        path: Updated canonical file.
        source: Existing provenance label.

    Returns:
        Whether the path belongs to a managed artifact.

    Raises:
        LibraryDataError: Reading, validating, or publishing the artifact fails.
    """
    artifact = artifact_for_path(path)
    if artifact is None:
        return False
    get_library_data_service().publish(artifact, source=source)
    return True


def hydrate_runtime_library_data(
    *,
    strict: bool = False,
) -> tuple[ArtifactStatus, ...]:
    """Hydrate files while retaining the existing local-fallback behavior.

    Args:
        strict: Whether store errors should propagate instead of using fallbacks.

    Returns:
        Hydration status in the original canonical artifact order.

    Raises:
        LibraryDataError: Hydration fails with strict mode enabled.
    """
    try:
        return get_library_data_service().hydrate_all()
    except LibraryDataError:
        if strict:
            raise
        _logger.warning(
            "Could not hydrate durable library data; using local fallback files.",
            exc_info=True,
        )
        return _fallback_statuses()


def _fallback_statuses() -> tuple[ArtifactStatus, ...]:
    statuses = []
    for name in ALL_ARTIFACTS:
        path = DEFAULT_ARTIFACT_PATHS[name]
        statuses.append(
            ArtifactStatus(
                name, path.name, path.exists(), None, None, None, None, False
            )
        )
    return tuple(statuses)
